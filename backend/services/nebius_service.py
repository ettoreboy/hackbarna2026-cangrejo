"""Nebius Token Factory analyzer. The primary provider.

OpenAI-compatible endpoint, so the official ``openai`` async client is used against
``https://api.tokenfactory.nebius.com/v1/``. Both pipeline steps go out as strict
``json_schema``; a model whose engine rejects strict mode falls back to ``json_object`` with
the key list restated in the prompt, and the downgrade is remembered per model for the
process. ``reasoning_effort`` is passed when configured (gpt-oss honours it: 3.7 s at "low"
versus 4.6 s default on the benchmark post).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TypeVar

from openai import APIStatusError, AsyncOpenAI, OpenAIError
from pydantic import BaseModel

from backend.config import Settings
from backend.prompts.claim_prompt import SYSTEM_CLAIM, build_claim_prompt
from backend.prompts.context_prompt import SYSTEM_PROMPTS, build_user_prompt
from backend.schemas.analysis_schema import AnalysisBody, AnalyzeRequest, MainClaim, Source
from backend.services.analyzer_base import AnalysisError, StepOutcome
from backend.services.pricing import cost_usd
from backend.services.schema_tools import RESPONSE_FORMAT_JSON_OBJECT, response_format_strict, schema_reminder

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)


def _strict_mode_rejected(exc: APIStatusError) -> bool:
    """True when the failure is 'this model cannot do strict schemas', not a real error."""
    if exc.status_code not in (400, 422, 501):
        return False
    blob = str(getattr(exc, "message", "") or exc).lower()
    return any(t in blob for t in ("json_schema", "response_format", "structured output", "strict", "schema"))


def _reasoning_rejected(exc: APIStatusError) -> bool:
    return exc.status_code in (400, 422) and "reasoning" in str(getattr(exc, "message", "") or exc).lower()


class NebiusAnalyzer:
    name = "nebius"

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        if not settings.nebius_configured:
            raise AnalysisError("NEBIUS_API_KEY is not set")
        self.settings = settings
        self.model = settings.nebius_model
        self.fast_model = settings.nebius_fast_model or settings.nebius_model
        self.reasoning_effort = settings.nebius_reasoning_effort or None
        self.client = client or AsyncOpenAI(
            base_url=settings.nebius_base_url,
            api_key=settings.nebius_api_key,
            timeout=settings.nebius_timeout_seconds,
            max_retries=1,
        )
        self._strict_ok: dict[str, bool] = {}
        self._formats = {
            MainClaim: response_format_strict("main_claim", MainClaim.model_json_schema()),
            AnalysisBody: response_format_strict("post_analysis", AnalysisBody.model_json_schema()),
        }

    # ------------------------------------------------------------------ transport

    async def _create(self, model: str, system: str, user: str, strict_format: dict | None, max_tokens: int):
        kwargs: dict = dict(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=strict_format or RESPONSE_FORMAT_JSON_OBJECT,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            return await self.client.chat.completions.create(**kwargs)
        except APIStatusError as exc:
            if self.reasoning_effort and _reasoning_rejected(exc):
                log.warning("%s rejected reasoning_effort; dropping it for this process", model)
                self.reasoning_effort = None
                kwargs.pop("reasoning_effort", None)
                return await self.client.chat.completions.create(**kwargs)
            raise

    async def _structured(self, model: str, system: str, user: str, out: type[M], max_tokens: int) -> StepOutcome[M]:
        strict_format = self._formats[out]
        try:
            if self._strict_ok.get(model, True):
                try:
                    completion = await self._create(model, system, user, strict_format, max_tokens)
                except APIStatusError as exc:
                    if not _strict_mode_rejected(exc):
                        raise
                    log.warning("%s rejected strict json_schema (%s); using json_object from now on", model, exc.status_code)
                    self._strict_ok[model] = False
                    completion = await self._create(model, system + schema_reminder(out), user, None, max_tokens)
            else:
                completion = await self._create(model, system + schema_reminder(out), user, None, max_tokens)
        except asyncio.TimeoutError as exc:
            raise AnalysisError(f"Nebius timed out after {self.settings.nebius_timeout_seconds}s") from exc
        except OpenAIError as exc:
            raise AnalysisError(f"Nebius call failed: {exc}") from exc

        if not completion.choices:
            raise AnalysisError("Nebius returned no choices")
        choice = completion.choices[0]
        content = choice.message.content
        finish = getattr(choice, "finish_reason", None)
        if not content:
            raise AnalysisError(f"Nebius returned empty content (finish_reason={finish})")
        if finish == "length":
            raise AnalysisError("Nebius hit the token limit before closing the JSON object")

        try:
            result = out.model_validate_json(content)
        except ValueError:
            salvaged = _extract_json_object(content)
            if salvaged is None:
                log.error("unparseable model output: %s", content[:500])
                raise AnalysisError("Nebius returned JSON that does not match the schema") from None
            try:
                result = out.model_validate(salvaged)
            except ValueError as exc:
                log.error("schema mismatch after salvage: %s", content[:500])
                raise AnalysisError("Nebius returned JSON that does not match the schema") from exc

        usage = completion.usage
        p_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        c_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        return StepOutcome(result=result, model=model, prompt_tokens=p_tok, completion_tokens=c_tok, cost_usd=cost_usd("nebius", model, p_tok, c_tok))

    # ------------------------------------------------------------------ pipeline steps

    async def extract_claim(self, req: AnalyzeRequest) -> StepOutcome[MainClaim]:
        return await self._structured(self.fast_model, SYSTEM_CLAIM, build_claim_prompt(req), MainClaim, max_tokens=300)

    async def analyse(
        self,
        req: AnalyzeRequest,
        claim: MainClaim,
        evidence: list[Source],
        background: list[Source],
        prompt_version: str = "v1",
    ) -> StepOutcome[AnalysisBody]:
        system = SYSTEM_PROMPTS[prompt_version]
        user = build_user_prompt(req, claim, evidence, background)
        return await self._structured(self.model, system, user, AnalysisBody, max_tokens=900)


def _extract_json_object(text: str) -> dict | None:
    """Pull the first balanced {...} out of a reply that carries extra prose or fences."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except ValueError:
                    return None
    return None
