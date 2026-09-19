"""Request/response contracts (schema v3, claim-first).

Two model-facing output shapes exist because the pipeline makes two calls:

- ``MainClaim``    step 1, claim extraction
- ``AnalysisBody`` step 3, claim check + missing context + rhetorical signals + speaker context

``PostAnalysis`` composes them for the client. The meaning of every field and every verdict
value is stated in the prompts (backend/prompts/*), because strict grammar mode on the
inference side does not surface schema descriptions to the model.

Contract changes must be mirrored in docs/API.md and tests/fixtures/responses_v3/.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from backend.prompts.taxonomy import normalize_label

SCHEMA_VERSION = "3"

Platform = Literal["x", "twitter", "instagram", "other"]
Verdict = Literal["supported", "partially_supported", "unsupported", "unverifiable", "no_factual_claim"]
VERDICTS: tuple[str, ...] = ("supported", "partially_supported", "unsupported", "unverifiable", "no_factual_claim")


# --------------------------------------------------------------------------- requests


class AnalyzeRequest(BaseModel):
    author_handle: str = Field(..., min_length=1, max_length=64, description="Handle, with or without leading @")
    author_name: str = Field(..., min_length=1, max_length=120)
    post_text: str = Field(..., min_length=1, max_length=8_000)
    platform: Platform = "x"
    post_url: HttpUrl | None = None

    @field_validator("author_handle")
    @classmethod
    def strip_at(cls, v: str) -> str:
        return v.lstrip("@").strip()


class AnalyzeMediaRequest(BaseModel):
    post_url: HttpUrl = Field(..., description="Canonical status URL of the post containing the video")
    author_handle: str = Field(..., min_length=1, max_length=64)
    author_name: str = Field(..., min_length=1, max_length=120)
    platform: Platform = "x"

    @field_validator("author_handle")
    @classmethod
    def strip_at(cls, v: str) -> str:
        return v.lstrip("@").strip()


# --------------------------------------------------------------------------- step 1 output


class MainClaim(BaseModel):
    found: bool
    text: str = Field(..., description="The claim as one standalone sentence; empty when found is false")
    quote: str = Field(..., description="Verbatim span of the post that carries the claim; empty when found is false")

    @model_validator(mode="after")
    def empty_when_not_found(self) -> "MainClaim":
        if not self.found:
            self.text = ""
            self.quote = ""
        return self


# --------------------------------------------------------------------------- step 3 output


class ClaimSource(BaseModel):
    title: str
    url: str


class ClaimCheck(BaseModel):
    verdict: Verdict
    explanation: str
    sources: list[ClaimSource]


class Signal(BaseModel):
    name: str
    evidence: str

    @field_validator("name")
    @classmethod
    def canonical(cls, v: str) -> str:
        return normalize_label(v)


class SpeakerContext(BaseModel):
    name: str
    role: str
    background: str


class AnalysisBody(BaseModel):
    claim_check: ClaimCheck
    missing_context: str
    rhetorical_signals: list[Signal]
    speaker_context: SpeakerContext

    @model_validator(mode="after")
    def dedupe_signals(self) -> "AnalysisBody":
        seen: set[str] = set()
        self.rhetorical_signals = [s for s in self.rhetorical_signals if not (s.name in seen or seen.add(s.name))]
        return self


# --------------------------------------------------------------------------- composed


class PostAnalysis(BaseModel):
    main_claim: MainClaim
    claim_check: ClaimCheck
    missing_context: str
    rhetorical_signals: list[Signal]
    speaker_context: SpeakerContext


# --------------------------------------------------------------------------- responses


class Source(BaseModel):
    title: str
    url: str
    snippet: str = ""
    provider: Literal["wikipedia", "brave"]


class Transcript(BaseModel):
    text: str
    language: str = "unknown"
    duration_s: float = 0
    stt_provider: str = ""
    stt_latency_ms: int = 0


class StepTimings(BaseModel):
    extract_ms: int = 0
    evidence_ms: int = 0
    analyse_ms: int = 0


class AnalyzeResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    analysis: PostAnalysis
    evidence: list[Source] = Field(default_factory=list, description="Web results the claim was checked against")
    sources: list[Source] = Field(default_factory=list, description="Author background sources")
    transcript: Transcript | None = None
    steps: StepTimings = Field(default_factory=StepTimings)
    cached: bool = False
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    cost_usd: float | None = None
    disclaimer: str = (
        "AI-generated analysis for media-literacy purposes. The verdict concerns one extracted claim, "
        "not the whole post. Verify against the listed sources."
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    schema_version: str = SCHEMA_VERSION
    providers: list[str]
    default_provider: str
    brave_configured: bool
    slng_configured: bool
