"""Provider-agnostic analyzer interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.schemas.analysis_schema import AnalysisResult, AnalyzeRequest, Source


class AnalysisError(RuntimeError):
    """Raised when the model call fails or returns unparseable output."""


@dataclass
class AnalysisOutcome:
    result: AnalysisResult
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None


class Analyzer(Protocol):
    name: str
    model: str

    async def analyze(
        self, req: AnalyzeRequest, sources: list[Source], prompt_version: str = "v1"
    ) -> AnalysisOutcome: ...
