"""Gemini analyzer via google-genai structured output. The baseline provider."""

from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from backend.config import Settings
from backend.prompts.context_prompt import SYSTEM_PROMPTS, build_user_prompt
from backend.schemas.analysis_schema import AnalysisResult, AnalyzeRequest, Source
from backend.services.analyzer_base import AnalysisError, AnalysisOutcome

log = logging.getLogger(__name__)

# USD per 1M tokens, Gemini 2.5 Flash paid tier (free tier is $0). Used only for the cost column.
_PRICES = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40)}


class GeminiAnalyzer:
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_configured:
            raise AnalysisError("GEMINI_API_KEY is not set")
        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model

    def _config(self, prompt_version: str) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPTS[prompt_version],
            response_mime_type="application/json",
            response_schema=AnalysisResult,
            temperature=0.2,
            max_output_tokens=1_600,
            # Political content is the whole point; keep the safety filter from silently blanking output.
            safety_settings=[
                types.SafetySetting(category=cat, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)
                for cat in (
                    types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                )
            ],
        )

    async def analyze(
        self, req: AnalyzeRequest, sources: list[Source], prompt_version: str = "v1"
    ) -> AnalysisOutcome:
        prompt = build_user_prompt(req, sources)
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model, contents=prompt, config=self._config(prompt_version)
                ),
                timeout=self.settings.gemini_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise AnalysisError(f"Gemini timed out after {self.settings.gemini_timeout_seconds}s") from exc
        except Exception as exc:  # SDK raises a family of google.genai.errors.*; surface as one type
            raise AnalysisError(f"Gemini call failed: {exc}") from exc

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, AnalysisResult):
            result = parsed
        else:
            text = getattr(response, "text", None)
            if not text:
                raise AnalysisError("Gemini returned no content (possibly blocked by safety filter)")
            try:
                result = AnalysisResult.model_validate_json(text)
            except ValueError as exc:
                log.error("unparseable model output: %s", text[:500])
                raise AnalysisError("Gemini returned JSON that does not match the schema") from exc

        usage = getattr(response, "usage_metadata", None)
        p_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
        c_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
        price = _PRICES.get(self.model)
        cost = (p_tok * price[0] + c_tok * price[1]) / 1_000_000 if price else None
        return AnalysisOutcome(result=result, model=self.model, prompt_tokens=p_tok, completion_tokens=c_tok, cost_usd=cost)
