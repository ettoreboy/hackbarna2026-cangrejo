"""Request/response contracts (schema v2).

AnalysisResult doubles as the structured-output schema sent to the model (Gemini
response_schema, Nebius json_schema). Field descriptions are model instructions:
keep them short and imperative. All fields are required so strict JSON mode works.

Contract changes must be mirrored in docs/API.md and tests/fixtures/responses_v2/.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from backend.prompts.taxonomy import normalize_label

SCHEMA_VERSION = "2"

Platform = Literal["x", "twitter", "instagram", "other"]
ScoreBand = Literal["low", "medium", "high"]
Provider = Literal["nebius", "gemini", "fake"]


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


# --------------------------------------------------------------------------- model output (v2)


class Signal(BaseModel):
    """A communication or emotional signal: a manipulation tactic and where it shows in the text."""

    name: str = Field(..., description="One of the ALLOWED communication_signals names")
    evidence: str = Field(..., description="Short verbatim quote from the post that shows the signal")
    confidence: float = Field(..., ge=0, le=1, description="0 to 1. Below 0.6 means uncertain")
    description: str = Field(..., description="One sentence on how the post uses it")

    @field_validator("name")
    @classmethod
    def canonical(cls, v: str) -> str:
        return normalize_label(v)


class Fallacy(BaseModel):
    name: str = Field(..., description="One of the ALLOWED logical_fallacies names")
    evidence: str = Field(..., description="Short verbatim quote from the post that contains the fallacy")

    @field_validator("name")
    @classmethod
    def canonical(cls, v: str) -> str:
        return normalize_label(v)


class Indicators(BaseModel):
    strategic_intent: str = Field(..., description="Why say this, now? The motive in plain words")
    timing_note: str = Field(
        ..., description="Election, news event or cycle the post rides on, or 'No timing signal identified'"
    )
    factual_context: str = Field(
        ...,
        description=(
            "Brief verifiable facts that clarify the claim. Only state facts supported by the provided "
            "sources or widely established; otherwise say what is unverified"
        ),
    )
    is_division_tactic: bool = Field(..., description="True if the persuasive force comes from group loyalty, not the claim")


class AnalysisResult(BaseModel):
    post_summary: str = Field(..., description="One or two neutral sentences saying what the post claims or asks")
    author: str = Field(..., description="Display name of the author as given")
    author_background: str = Field(
        ...,
        description=(
            "Neutral 1-3 sentence summary of the author's public role. If no source was provided and the "
            "author is not widely known, write exactly 'Unknown author'"
        ),
    )
    communication_signals: list[Signal] = Field(..., description="Empty list if the post is informational")
    logical_fallacies: list[Fallacy] = Field(..., description="Empty list if none")
    indicators: Indicators
    manipulation_score: int = Field(..., ge=0, le=100, description="0 = informational, 100 = pure manipulation")
    cognitive_summary: str = Field(
        ..., description="One paragraph teaching the reader the general pattern so they recognise it next time"
    )

    @model_validator(mode="after")
    def dedupe_labels(self) -> "AnalysisResult":
        seen: set[str] = set()
        self.communication_signals = [s for s in self.communication_signals if not (s.name in seen or seen.add(s.name))]
        seen.clear()
        self.logical_fallacies = [f for f in self.logical_fallacies if not (f.name in seen or seen.add(f.name))]
        return self

    @property
    def score_band(self) -> ScoreBand:
        if self.manipulation_score < 34:
            return "low"
        if self.manipulation_score < 67:
            return "medium"
        return "high"


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


class AnalyzeResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    analysis: AnalysisResult
    score_band: ScoreBand
    sources: list[Source] = Field(default_factory=list)
    transcript: Transcript | None = None
    cached: bool = False
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    cost_usd: float | None = None
    disclaimer: str = (
        "AI-generated analysis for media-literacy purposes. Not a fact-check. "
        "Verify claims against the listed sources."
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    schema_version: str = SCHEMA_VERSION
    providers: list[str]
    default_provider: str
    brave_configured: bool
    slng_configured: bool
