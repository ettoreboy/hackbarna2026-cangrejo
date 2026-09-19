"""POST /api/v1/analyze, GET /api/v1/health. (/analyze-media arrives with the SLNG work package.)"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas.analysis_schema import AnalyzeRequest, AnalyzeResponse, HealthResponse
from backend.services.analyzer_base import AnalysisError, Analyzer
from backend.services.cache import make_key
from backend.services.pipeline import run_pipeline

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["analyze"])


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
    nocache: bool = Query(default=False),
) -> AnalyzeResponse:
    analyzer = pick_analyzer(request, provider)
    cache = request.app.state.cache

    key = make_key(f"{analyzer.name}:{analyzer.model}:{prompt_version}:{req.author_handle}", req.post_text)
    if not nocache and (hit := cache.get(key)) is not None:
        return hit.model_copy(update={"cached": True, "latency_ms": 0})

    try:
        response = await run_pipeline(
            req, analyzer, request.app.state.http, request.app.state.settings, prompt_version,
            cache=request.app.state.search_cache,
        )
    except AnalysisError as exc:
        log.warning("analysis failed for @%s via %s: %s", req.author_handle, analyzer.name, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.set(key, response)
    return response
