"""GET /api/v1/health, POST /api/v1/analyze, /claims, /analyze-claim. (No media route: see docs/API.md.)"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas.analysis_schema import (
    AnalyzeClaimRequest,
    AnalyzeRequest,
    AnalyzeResponse,
    ClaimAnalysisResponse,
    ClaimsResponse,
    HealthResponse,
)
from backend.services.analyzer_base import AnalysisError, Analyzer
from backend.services.cache import context_key, make_key
from backend.services.pipeline import check_one_claim, discover_claims, run_pipeline
from backend.services.text_tools import snap_quote

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["analyze"])


def _ctx_key(req: AnalyzeRequest) -> str:
    """The quoted post and the links change the answer, so they have to change the key."""
    return context_key(req.links, req.quoted_post.text if req.quoted_post else "")


def pick_analyzer(request: Request, provider: str | None) -> Analyzer:
    analyzers: dict[str, Analyzer] = request.app.state.analyzers
    if not analyzers:
        raise HTTPException(status_code=503, detail="No analyzer configured: set NEBIUS_API_KEY or GEMINI_API_KEY, or ANALYZER_PROVIDER=fake")
    name = provider or request.app.state.default_provider
    if name not in analyzers:
        raise HTTPException(status_code=400, detail=f"Unknown or unconfigured provider '{name}'. Available: {sorted(analyzers)}")
    return analyzers[name]


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        providers=sorted(request.app.state.analyzers),
        default_provider=request.app.state.default_provider or "",
        brave_configured=settings.brave_configured,
        brave_live_calls=request.app.state.search_cache.live_calls(),
        brave_budget=settings.brave_budget,
        slng_configured=settings.slng_configured,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    req: AnalyzeRequest,
    request: Request,
    provider: str | None = Query(default=None, description="nebius | gemini | fake; defaults to ANALYZER_PROVIDER"),
    prompt_version: str = Query(default="v1", pattern="^v[01]$", description="v0 = task only, v1 = guarded"),
    rigor: str | None = Query(default=None, pattern="^(standard|strict)$",
                             description="standard = as measured in docs/EVAL.md; strict = look harder at framing"),
    nocache: bool = Query(default=False),
) -> AnalyzeResponse:
    analyzer = pick_analyzer(request, provider)
    cache = request.app.state.cache
    rigor = rigor or request.app.state.settings.analyzer_rigor
    # Only non-default rigor joins the cache key, so rows written before the knob
    # existed stay reachable and a strict run can never serve a standard answer.
    rigor_key = "" if rigor == "standard" else f":{rigor}"

    key = make_key(f"{analyzer.name}:{analyzer.model}:{prompt_version}{rigor_key}:{req.author_handle}{_ctx_key(req)}", req.post_text)
    if not nocache and (hit := cache.get(key)) is not None:
        return hit.model_copy(update={"cached": True, "latency_ms": 0})

    try:
        response = await run_pipeline(
            req, analyzer, request.app.state.http, request.app.state.settings, prompt_version, rigor,
            cache=request.app.state.search_cache,
        )
    except AnalysisError as exc:
        log.warning("analysis failed for @%s via %s: %s", req.author_handle, analyzer.name, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.set(key, response)
    return response


# --------------------------------------------------------------------------- two-stage flow


@router.post("/claims", response_model=ClaimsResponse)
async def claims(
    req: AnalyzeRequest,
    request: Request,
    provider: str | None = Query(default=None, description="nebius | gemini | fake; defaults to ANALYZER_PROVIDER"),
    prompt_version: str = Query(default="v1", pattern="^v[01]$"),
    rigor: str | None = Query(default=None, pattern="^(standard|strict)$",
                             description="standard = as measured in docs/EVAL.md; strict = look harder at framing"),
    nocache: bool = Query(default=False),
) -> ClaimsResponse:
    """Stage 1: what is checkable in this post, how it is written, and who is speaking.

    No claim is checked here. The reader picks one and calls /analyze-claim with it.
    """
    analyzer = pick_analyzer(request, provider)
    cache = request.app.state.cache
    rigor = rigor or request.app.state.settings.analyzer_rigor
    # Only non-default rigor joins the cache key, so rows written before the knob
    # existed stay reachable and a strict run can never serve a standard answer.
    rigor_key = "" if rigor == "standard" else f":{rigor}"

    key = make_key(f"claims:{analyzer.name}:{analyzer.model}:{prompt_version}{rigor_key}:{req.author_handle}{_ctx_key(req)}", req.post_text)
    if not nocache and (hit := cache.get(key)) is not None:
        return hit.model_copy(update={"cached": True, "latency_ms": 0})

    try:
        response = await discover_claims(
            req, analyzer, request.app.state.http, request.app.state.settings, prompt_version, rigor,
            cache=request.app.state.search_cache,
        )
    except AnalysisError as exc:
        log.warning("claim discovery failed for @%s via %s: %s", req.author_handle, analyzer.name, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.set(key, response)
    return response


@router.post("/analyze-claim", response_model=ClaimAnalysisResponse)
async def analyze_claim(
    req: AnalyzeClaimRequest,
    request: Request,
    provider: str | None = Query(default=None, description="nebius | gemini | fake; defaults to ANALYZER_PROVIDER"),
    prompt_version: str = Query(default="v1", pattern="^v[01]$"),
    rigor: str | None = Query(default=None, pattern="^(standard|strict)$",
                             description="standard = as measured in docs/EVAL.md; strict = look harder at framing"),
    nocache: bool = Query(default=False),
) -> ClaimAnalysisResponse:
    """Stage 2: check the one claim the reader picked against web evidence."""
    analyzer = pick_analyzer(request, provider)
    cache = request.app.state.cache
    rigor = rigor or request.app.state.settings.analyzer_rigor
    # Only non-default rigor joins the cache key, so rows written before the knob
    # existed stay reachable and a strict run can never serve a standard answer.
    rigor_key = "" if rigor == "standard" else f":{rigor}"

    # The claim must come from the post. Without this a client could hand us arbitrary text
    # and have the model check it as though someone had posted it.
    if not req.claim.text.strip():
        raise HTTPException(status_code=422, detail="claim.text must not be empty")
    if snap_quote(req.post_text, req.claim.quote) is None:
        raise HTTPException(status_code=422, detail="claim.quote is not present in post_text")

    key = make_key(
        f"claim:{analyzer.name}:{analyzer.model}:{prompt_version}{rigor_key}:{req.author_handle}{_ctx_key(req)}:{req.claim.id}",
        req.post_text + "\x00" + req.claim.text,
    )
    if not nocache and (hit := cache.get(key)) is not None:
        return hit.model_copy(update={"cached": True, "latency_ms": 0})

    try:
        response = await check_one_claim(
            req, analyzer, request.app.state.http, request.app.state.settings, prompt_version, rigor,
            cache=request.app.state.search_cache,
        )
    except AnalysisError as exc:
        log.warning("claim check failed for @%s via %s: %s", req.author_handle, analyzer.name, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.set(key, response)
    return response
