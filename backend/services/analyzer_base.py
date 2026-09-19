"""Provider-agnostic analyzer interface for the two model calls of the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from backend.schemas.analysis_schema import AnalysisBody, AnalyzeRequest, MainClaim, Source

T = TypeVar("T")


class AnalysisError(RuntimeError):
    """Raised when a model call fails or returns unparseable output."""


@dataclass
class StepOutcome(Generic[T]):
    result: T
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None


class Analyzer(Protocol):
    name: str
    model: str

    async def extract_claim(self, req: AnalyzeRequest) -> StepOutcome[MainClaim]: ...

    async def analyse(
        self,
        req: AnalyzeRequest,
        claim: MainClaim,
        evidence: list[Source],
        background: list[Source],
        prompt_version: str = "v1",
    ) -> StepOutcome[AnalysisBody]: ...
