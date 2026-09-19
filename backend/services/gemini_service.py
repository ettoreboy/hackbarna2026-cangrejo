"""Gemini analyzer via google-genai structured output. The baseline provider."""

from __future__ import annotations

import asyncio
import logging
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from backend.config import Settings
from backend.prompts.claim_prompt import SYSTEM_CLAIM, build_claim_prompt
from backend.prompts.context_prompt import SYSTEM_PROMPTS, build_user_prompt
from backend.schemas.analysis_schema import AnalysisBody, AnalyzeRequest, MainClaim, Source
from backend.services.analyzer_base import AnalysisError, StepOutcome
from backend.services.pricing import cost_usd

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

# Political content is the point; keep the safety filter from silently blanking output.
_SAFETY = [
    types.SafetySetting(category=cat, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)
    for cat in (
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    )
]


class GeminiAnalyzer:
    name = "gemini"

    def __init__(self, settings: Settings, client: genai.Client | None = None) -> None:
        if not settings.gemini_configured:
            raise AnalysisError("GEMINI_API_KEY is not set")
        self.settings = settings
        self.client = client or genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model
        self.temperature = settings.gemini_temperature

    async def _structured(self, system: str, user: str, out: type[M], max_tokens: int) -> StepOutcome[M]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=out,
            temperature=self.temperature,
            max_output_tokens=max_tokens,
            safety_settings=_SAFETY,
        )
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(model=self.model, contents=user, config=config),
                timeout=self.settings.gemini_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise AnalysisError(f"Gemini timed out after {self.settings.gemini_timeout_seconds}s") from exc
        except Exception as exc:  # the SDK raises a family of google.genai.errors.*
            raise AnalysisError(f"Gemini call failed: {exc}") from exc

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, out):
            result = parsed
        else:
            text = getattr(response, "text", None)
            if not text:
                raise AnalysisError("Gemini returned no content (possibly blocked by safety filter)")
            try:
                result = out.model_validate_json(text)
            except ValueError as exc:
                log.error("unparseable model output: %s", text[:500])
                raise AnalysisError("Gemini returned JSON that does not match the schema") from exc

        usage = getattr(response, "usage_metadata", None)
        p_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
        c_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
        return StepOutcome(
            result=result,
            model=self.model,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_usd=cost_usd("gemini", self.model, p_tok, c_tok),
        )

    async def extract_claim(self, req: AnalyzeRequest) -> StepOutcome[MainClaim]:
        return await self._structured(SYSTEM_CLAIM, build_claim_prompt(req), MainClaim, max_tokens=300)

    async def analyse(
        self,
        req: AnalyzeRequest,
        claim: MainClaim,
        evidence: list[Source],
        background: list[Source],
        prompt_version: str = "v1",
    ) -> StepOutcome[AnalysisBody]:
        return await self._structured(
            SYSTEM_PROMPTS[prompt_version],
            build_user_prompt(req, claim, evidence, background),
            AnalysisBody,
            max_tokens=900,
        )
