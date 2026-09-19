"""Nebius Token Factory analyzer. The primary provider.

OpenAI-compatible endpoint, so the official ``openai`` async client is used against
``https://api.tokenfactory.nebius.com/v1/``. Structured output goes out as a strict
``json_schema``; models whose serving engine rejects strict mode fall back to
``json_object`` with the schema restated in the prompt, and the model id is remembered so
the retry happens once per process, not once per request.
"""

from __future__ import annotations

import asyncio
import json
import logging

from openai import APIStatusError, AsyncOpenAI, OpenAIError

from backend.config import Settings
from backend.prompts.context_prompt import SYSTEM_PROMPTS, build_user_prompt
from backend.schemas.analysis_schema import AnalysisResult, AnalyzeRequest, Source
from backend.services.analyzer_base import AnalysisError, AnalysisOutcome
from backend.services.pricing import cost_usd
from backend.services.schema_tools import (
    RESPONSE_FORMAT_JSON_OBJECT,
    response_format_strict,
    to_strict_schema,
)

log = logging.getLogger(__name__)

_SCHEMA_NAME = "context_guard_analysis"

# Appended to the system prompt only on the json_object fallback path, where the engine
# enforces "valid JSON" but not "this shape".
_SCHEMA_REMINDER = (
    "\nReturn a single JSON object with exactly these keys: post_summary (string), "
    "author (string), author_background (string), communication_signals (array of objects "
    "with name, evidence, confidence, description), logical_fallacies (array of objects with "
    "name, evidence), indicators (object with strategic_intent, timing_note, factual_context, "
    "is_division_tactic), manipulation_score (integer 0-100), cognitive_summary (string). "
    "No prose outside the JSON."
)


def _strict_mode_rejected(exc: APIStatusError) -> bool:
    """True when the failure is 'this model cannot do strict schemas', not a real error."""
    if exc.status_code not in (400, 422, 501):
        return False
    blob = str(getattr(exc, "message", "") or exc).lower()
    return any(
        token in blob
        for token in ("json_schema", "response_format", "structured output", "strict", "schema")
    )


class NebiusAnalyzer:
    name = "nebius"

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        if not settings.nebius_configured:
            raise AnalysisError("NEBIUS_API_KEY is not set")
        self.settings = settings
        self.model = settings.nebius_model
        self.client = client or AsyncOpenAI(
            base_url=settings.nebius_base_url,
            api_key=settings.nebius_api_key,
            timeout=settings.nebius_timeout_seconds,
            max_retries=1,
        )
        self._strict_schema = to_strict_schema(AnalysisResult.model_json_schema())
        self._response_format = response_format_strict(_SCHEMA_NAME, AnalysisResult.model_json_schema())
        self._use_strict = True

    async def _call(self, system: str, user: str, strict: bool):
        return await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=self._response_format if strict else RESPONSE_FORMAT_JSON_OBJECT,
            temperature=0.2,
            max_tokens=1_600,
        )

    async def analyze(
        self, req: AnalyzeRequest, sources: list[Source], prompt_version: str = "v1"
    ) -> AnalysisOutcome:
        system = SYSTEM_PROMPTS[prompt_version]
        user = build_user_prompt(req, sources)

        try:
            if self._use_strict:
                try:
                    completion = await self._call(system, user, strict=True)
                except APIStatusError as exc:
                    if not _strict_mode_rejected(exc):
                        raise
                    log.warning(
                        "%s rejected strict json_schema (%s); falling back to json_object for this process",
                        self.model,
                        exc.status_code,
                    )
                    self._use_strict = False
                    completion = await self._call(system + _SCHEMA_REMINDER, user, strict=False)
            else:
                completion = await self._call(system + _SCHEMA_REMINDER, user, strict=False)
        except asyncio.TimeoutError as exc:
            raise AnalysisError(f"Nebius timed out after {self.settings.nebius_timeout_seconds}s") from exc
        except OpenAIError as exc:
            raise AnalysisError(f"Nebius call failed: {exc}") from exc

        if not completion.choices:
            raise AnalysisError("Nebius returned no choices")
        choice = completion.choices[0]
        content = choice.message.content
        if not content:
            reason = getattr(choice, "finish_reason", "unknown")
            raise AnalysisError(f"Nebius returned empty content (finish_reason={reason})")
        if getattr(choice, "finish_reason", None) == "length":
            raise AnalysisError("Nebius hit the token limit before closing the JSON object")

        try:
            result = AnalysisResult.model_validate_json(content)
        except ValueError:
            # Some models wrap the object in a fenced block or add a preamble.
            salvaged = _extract_json_object(content)
            if salvaged is None:
                log.error("unparseable model output: %s", content[:500])
                raise AnalysisError("Nebius returned JSON that does not match the schema") from None
            try:
                result = AnalysisResult.model_validate(salvaged)
            except ValueError as exc:
                log.error("schema mismatch after salvage: %s", content[:500])
                raise AnalysisError("Nebius returned JSON that does not match the schema") from exc

        usage = completion.usage
        p_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        c_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        return AnalysisOutcome(
            result=result,
            model=self.model,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_usd=cost_usd("nebius", self.model, p_tok, c_tok),
        )


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
