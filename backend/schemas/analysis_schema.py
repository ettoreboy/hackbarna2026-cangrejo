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


class AnalyzeClaimRequest(AnalyzeRequest):
    """Stage 2: the post, plus the claim the reader picked out of stage 1."""

    claim: "ClaimCandidate"


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


def dedupe_signal_list(signals: list[Signal]) -> list[Signal]:
    """One label once, and one span of the post tagged once.

    Deduping on the label alone left 17% of analyses with the same words highlighted twice,
    including six where two labels carried a byte-identical quote. The client highlights these
    spans, so an overlap renders as a double underline on the same phrase. The longer quote
    wins, since it is the one that carries the context.

    Shared by AnalysisBody (/analyze) and DiscoveryBody (/claims): both feed the same renderer.
    """
    kept: list[Signal] = []
    seen_names: set[str] = set()
    for sig in sorted(signals, key=lambda s: len(s.evidence), reverse=True):
        if sig.name in seen_names:
            continue
        span = sig.evidence.strip()
        if span and any(span in k.evidence or k.evidence in span for k in kept):
            continue
        seen_names.add(sig.name)
        kept.append(sig)
    order = {id(s): i for i, s in enumerate(signals)}
    return sorted(kept, key=lambda s: order[id(s)])


class AnalysisBody(BaseModel):
    claim_check: ClaimCheck
    missing_context: str
    rhetorical_signals: list[Signal]
    speaker_context: SpeakerContext

    @model_validator(mode="after")
    def dedupe_signals(self) -> "AnalysisBody":
        self.rhetorical_signals = dedupe_signal_list(self.rhetorical_signals)
        return self


# --------------------------------------------------------------------------- composed


class PostAnalysis(BaseModel):
    main_claim: MainClaim
    claim_check: ClaimCheck
    missing_context: str
    rhetorical_signals: list[Signal]
    speaker_context: SpeakerContext


# --------------------------------------------------------------------------- two-stage (claim picker)
#
# The one-shot /analyze above picks the claim itself. The two-stage flow hands that choice to
# the reader instead, and the fields split cleanly by scope:
#
#   stage 1  /claims        post-level:  claims[], rhetorical_signals, speaker_context
#   stage 2  /analyze-claim claim-level: claim_check, missing_context, evidence
#
# So the Wikipedia lookup and the signal pass run once per post, and checking a second claim
# costs one search plus one model call.


class ClaimDraft(BaseModel):
    """One candidate claim as the model returns it, before the server assigns an id."""

    text: str = Field(..., description="The claim as one standalone, checkable sentence")
    quote: str = Field(..., description="Verbatim span of the post that carries the claim")


class ClaimCandidate(BaseModel):
    """A candidate claim with a stable id the client sends back in stage 2."""

    id: str
    text: str
    quote: str


class DiscoveryBody(BaseModel):
    """Stage 1 model output. Every field required so strict JSON mode works."""

    claims: list[ClaimDraft]
    rhetorical_signals: list[Signal]
    speaker_context: SpeakerContext

    @model_validator(mode="after")
    def dedupe(self) -> "DiscoveryBody":
        self.rhetorical_signals = dedupe_signal_list(self.rhetorical_signals)
        # Same reasoning for claims: two entries whose quotes overlap are one claim said twice,
        # and the reader would be picking between duplicates. The longer span wins.
        kept: list[ClaimDraft] = []
        for claim in sorted(self.claims, key=lambda c: len(c.quote), reverse=True):
            span = claim.quote.strip()
            if not span or any(span in k.quote or k.quote in span for k in kept):
                continue
            kept.append(claim)
        order = {id(c): i for i, c in enumerate(self.claims)}
        self.claims = sorted(kept, key=lambda c: order[id(c)])
        return self


class ClaimVerdict(BaseModel):
    """Stage 2 model output: the verdict on one claim, and what context is missing."""

    claim_check: ClaimCheck
    missing_context: str


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


class ClaimsResponse(BaseModel):
    """Stage 1: what is checkable in this post, plus everything post-level."""

    schema_version: str = SCHEMA_VERSION
    claims: list[ClaimCandidate] = Field(default_factory=list, description="Most central first; empty means nothing checkable")
    rhetorical_signals: list[Signal] = Field(default_factory=list)
    speaker_context: SpeakerContext
    sources: list[Source] = Field(default_factory=list, description="Author background sources")
    evidence: list[Source] = Field(
        default_factory=list,
        description="Web results related to this post. Stage 1 searches the post itself; picking a claim re-searches for that claim.",
    )
    transcript: Transcript | None = None
    steps: StepTimings = Field(default_factory=StepTimings)
    cached: bool = False
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    cost_usd: float | None = None
    disclaimer: str = (
        "AI-generated analysis for media-literacy purposes. Not a fact-check. "
        "Pick a claim to check it against the web."
    )


class ClaimAnalysisResponse(BaseModel):
    """Stage 2: the verdict on the one claim the reader picked."""

    schema_version: str = SCHEMA_VERSION
    claim: ClaimCandidate
    claim_check: ClaimCheck
    missing_context: str = ""
    evidence: list[Source] = Field(default_factory=list, description="Web results the claim was checked against")
    steps: StepTimings = Field(default_factory=StepTimings)
    cached: bool = False
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    cost_usd: float | None = None
    disclaimer: str = (
        "AI-generated analysis for media-literacy purposes. The verdict concerns this one claim, "
        "not the whole post. Verify against the listed sources."
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    schema_version: str = SCHEMA_VERSION
    providers: list[str]
    default_provider: str
    brave_configured: bool
    brave_live_calls: int = 0
    brave_budget: int = 0
    slng_configured: bool


# --------------------------------------------------------------------------- comparison
#
# Additive to schema v3: nothing above this line changes, so SCHEMA_VERSION stays "3".
# These types exist for the comparison runner (scripts/compare.py, POST /api/v1/compare),
# which puts one post through several provider x prompt_version arms side by side.


class Variant(BaseModel):
    """One arm of a comparison: a provider, optionally a specific model, and a prompt version.

    ``model`` is how two models on the same provider are put side by side. It is deliberately
    only on this type: the model is internal configuration and is never selectable from the
    extension, so /analyze, /claims and /analyze-claim take no model parameter.
    """

    provider: str = Field(..., min_length=1, description="nebius | gemini | fake")
    model: str = Field(default="", max_length=128, description="Provider model id; empty = the provider's configured default")
    prompt_version: Literal["v0", "v1"] = "v1"
    # How hard the arm looks at framing. Orthogonal to prompt_version: v1 is the guardrails,
    # rigor is the scrutiny level applied on top of them. "standard" leaves every prompt byte
    # for byte as docs/EVAL.md measured it, so a rigor arm never disturbs the v0/v1 ablation.
    rigor: Literal["standard", "strict"] = "standard"
    label: str = Field(default="", max_length=64, description="Display name; defaults to provider:prompt_version")

    def resolved_label(self) -> str:
        """An explicit label, else provider:version, else the short model name and the version.

        Named models label by model rather than by provider, because the provider is the thing
        held constant in that comparison and repeating it in every column says nothing. The
        full id stays on ``VariantArm.model``.
        """
        if self.label:
            return self.label
        head = self.provider if not self.model else self.model.rsplit("/", 1)[-1]
        tail = self.prompt_version if self.rigor == "standard" else f"{self.prompt_version}+{self.rigor}"
        return f"{head}:{tail}"


class CompareRequest(AnalyzeRequest):
    variants: list[Variant] = Field(..., min_length=2, max_length=4)


class VariantArm(BaseModel):
    label: str
    provider: str
    prompt_version: str
    rigor: str = "standard"
    model: str = ""
    response: AnalyzeResponse | None = None
    error: str | None = Field(default=None, description="Set when this arm failed; the other arms still ran")
    warnings: list[str] = Field(default_factory=list, description="Quote fidelity, taxonomy and citation problems")

    @property
    def ok(self) -> bool:
        return self.response is not None


class CompareDiff(BaseModel):
    """Agreement between arms. Rates are over unordered arm pairs; None when fewer than two arms succeeded."""

    claim_agreement: float | None = Field(default=None, description="Share of arm pairs that extracted the same claim")
    verdict_agreement: float | None = Field(default=None, description="Share of arm pairs with the same verdict")
    signal_overlap: float | None = Field(default=None, description="Mean pairwise Jaccard over signal name sets")
    verdicts: dict[str, str] = Field(default_factory=dict)
    signals: dict[str, list[str]] = Field(default_factory=dict)
    latency_ms: dict[str, int] = Field(default_factory=dict)
    cost_usd: dict[str, float | None] = Field(default_factory=dict)


class CompareResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    post_text: str
    author_handle: str
    arms: list[VariantArm]
    diff: CompareDiff = Field(default_factory=CompareDiff)
    evidence: list[Source] = Field(default_factory=list, description="Evidence of the first successful arm; shared by later arms via the search cache")
    sources: list[Source] = Field(default_factory=list, description="Author background of the first successful arm; shared by later arms via the search cache")
    total_latency_ms: int = 0
    total_cost_usd: float | None = None
    disclaimer: str = (
        "AI-generated analysis for media-literacy purposes. A disagreement between arms is a "
        "property of the models, not evidence that either verdict is correct."
    )
