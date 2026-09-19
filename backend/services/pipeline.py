"""The claim-first pipeline: extract → evidence → analyse.

Step 1 and the author background lookup are independent and run concurrently. The claim
search waits for step 1. Step 3 waits for everything. Cited sources are filtered to URLs that
were actually in the evidence, so a hallucinated link can never reach the client.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from backend.config import Settings
from backend.schemas.analysis_schema import (
    AnalyzeResponse,
    AnalyzeRequest,
    ClaimCheck,
    ClaimSource,
    PostAnalysis,
    Source,
    StepTimings,
    Transcript,
)
from backend.services.analyzer_base import Analyzer
from backend.services.background_service import get_author_background
from backend.services.evidence_service import search_claim
from backend.services.search_cache import SearchCache


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _cited_only(check: ClaimCheck, evidence: list[Source]) -> ClaimCheck:
    by_url = {s.url.rstrip("/"): s for s in evidence}
    kept: list[ClaimSource] = []
    seen: set[str] = set()
    for cited in check.sources:
        key = cited.url.rstrip("/")
        src = by_url.get(key)
        if src is None or key in seen:
            continue
        seen.add(key)
        kept.append(ClaimSource(title=src.title, url=src.url))
    return check.model_copy(update={"sources": kept})


async def run_pipeline(
    req: AnalyzeRequest,
    analyzer: Analyzer,
    http: httpx.AsyncClient,
    settings: Settings,
    prompt_version: str = "v1",
    transcript: Transcript | None = None,
    cache: SearchCache | None = None,
) -> AnalyzeResponse:
    total_started = time.perf_counter()
    timings = StepTimings()

    # Step 1 + author background, concurrently.
    t0 = time.perf_counter()
    claim_outcome, background = await asyncio.gather(
        analyzer.extract_claim(req),
        get_author_background(http, settings, req.author_name, req.author_handle, cache),
    )
    timings.extract_ms = _ms(t0)
    claim = claim_outcome.result

    # Step 2.
    t0 = time.perf_counter()
    evidence = await search_claim(http, settings, claim, cache)
    timings.evidence_ms = _ms(t0)

    # Step 3.
    t0 = time.perf_counter()
    body_outcome = await analyzer.analyse(req, claim, evidence, background, prompt_version=prompt_version)
    timings.analyse_ms = _ms(t0)
    body = body_outcome.result

    check = _cited_only(body.claim_check, evidence)
    if not claim.found and check.verdict != "no_factual_claim":
        check = check.model_copy(update={"verdict": "no_factual_claim", "sources": []})

    analysis = PostAnalysis(
        main_claim=claim,
        claim_check=check,
        missing_context=body.missing_context,
        rhetorical_signals=body.rhetorical_signals,
        speaker_context=body.speaker_context,
    )
    costs = [c for c in (claim_outcome.cost_usd, body_outcome.cost_usd) if c is not None]
    return AnalyzeResponse(
        analysis=analysis,
        evidence=evidence,
        sources=background,
        transcript=transcript,
        steps=timings,
        latency_ms=_ms(total_started),
        provider=analyzer.name,
        model=body_outcome.model,
        cost_usd=sum(costs) if costs else None,
    )
