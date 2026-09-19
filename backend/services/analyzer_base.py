"""Provider-agnostic analyzer interface for the two model calls of the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from backend.schemas.analysis_schema import (
    AnalysisBody,
    AnalyzeRequest,
    ClaimCandidate,
    ClaimVerdict,
    DiscoveryBody,
    MainClaim,
    Source,
)

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

    def with_model(self, model: str) -> "Analyzer":
        """Return an analyzer identical to this one but running `model`.

        Used by /compare to put two models of one provider side by side. It lives on the
        provider because only the provider knows which of its settings name a model, and it
        should share the underlying HTTP client rather than open a second connection pool.
        Returning `self` for an empty or unchanged model is the expected no-op.
        """
        ...

    # -- one-shot pipeline (/analyze) ---------------------------------------

    async def extract_claim(self, req: AnalyzeRequest) -> StepOutcome[MainClaim]: ...

    async def analyse(
        self,
        req: AnalyzeRequest,
        claim: MainClaim,
        evidence: list[Source],
        background: list[Source],
        prompt_version: str = "v1",
    ) -> StepOutcome[AnalysisBody]: ...

    # -- two-stage claim picker (/claims, /analyze-claim) --------------------

    async def discover(
        self,
        req: AnalyzeRequest,
        background: list[Source],
        max_claims: int = 4,
        prompt_version: str = "v1",
    ) -> StepOutcome[DiscoveryBody]:
        """Stage 1: every checkable claim, the rhetorical signals, and who is speaking."""
        ...

    async def check_claim(
        self,
        req: AnalyzeRequest,
        claim: ClaimCandidate,
        evidence: list[Source],
        prompt_version: str = "v1",
    ) -> StepOutcome[ClaimVerdict]:
        """Stage 2: verdict on the one claim the reader picked, plus what context is missing."""
        ...
