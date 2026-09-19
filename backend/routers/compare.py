"""POST /api/v1/compare: one post, several provider x prompt_version arms, side by side."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas.analysis_schema import AnalyzeRequest, CompareRequest, CompareResponse
from backend.services.compare import UnknownProvider, run_compare

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["compare"])


@router.post("/compare", response_model=CompareResponse)
async def compare(
    req: CompareRequest,
    request: Request,
    nocache: bool = Query(default=False, description="Skip the response cache; arms are still cached afterwards"),
) -> CompareResponse:
    analyzers = request.app.state.analyzers
    if not analyzers:
        raise HTTPException(status_code=503, detail="No analyzer configured: set NEBIUS_API_KEY or GEMINI_API_KEY, or ANALYZER_PROVIDER=fake")

    analyze_req = AnalyzeRequest(**req.model_dump(exclude={"variants"}))
    try:
        result = await run_compare(
            analyze_req,
            req.variants,
            analyzers,
            request.app.state.http,
            request.app.state.settings,
            search_cache=request.app.state.search_cache,
            cache=None if nocache else request.app.state.cache,
        )
    except UnknownProvider as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if all(arm.error for arm in result.arms):
        raise HTTPException(status_code=502, detail="; ".join(f"{a.label}: {a.error}" for a in result.arms))
    return result
