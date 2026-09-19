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
    AnalyzeClaimRequest,
    AnalyzeRequest,
    ClaimAnalysisResponse,
    ClaimCandidate,
    ClaimCheck,
    ClaimSource,
    ClaimsResponse,
    MainClaim,
    PostAnalysis,
    Source,
    StepTimings,
    Transcript,
)
from backend.services.analyzer_base import Analyzer
from backend.services.background_service import get_author_background
from backend.services.evidence_service import search_claim
from backend.services.search_cache import SearchCache
from backend.services.text_tools import snap_quote


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


def _snap_signals(signals, post: str):
    """Replace each quote with the exact span of the post it refers to; drop ones that are not there.

    Models normalise typography when copying (a non-breaking hyphen becomes "-"), which would
    leave the extension unable to highlight the span it was handed.
    """
    kept = []
    for sig in signals:
        exact = snap_quote(post, sig.evidence)
        if exact is not None:
            kept.append(sig.model_copy(update={"evidence": exact}))
    return kept


def _snap_quotes(body, post: str):
    return body.model_copy(update={"rhetorical_signals": _snap_signals(body.rhetorical_signals, post)})


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

    body = _snap_quotes(body, req.post_text)
    if claim.found and claim.quote:
        exact_claim = snap_quote(req.post_text, claim.quote)
        claim = claim.model_copy(update={"quote": exact_claim or ""})

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


# --------------------------------------------------------------------------- two-stage flow
#
# Same three steps, cut between the reader's choice:
#
#   discover_claims  step 1  what is checkable, how it is written, who is speaking
#   ...reader picks a claim...
#   check_one_claim  steps 2 and 3, for that claim alone
#
# The author lookup and the signal pass happen once, in stage 1, so checking a second claim
# costs one search plus one model call.


async def discover_claims(
    req: AnalyzeRequest,
    analyzer: Analyzer,
    http: httpx.AsyncClient,
    settings: Settings,
    prompt_version: str = "v1",
    transcript: Transcript | None = None,
    cache: SearchCache | None = None,
) -> ClaimsResponse:
    total_started = time.perf_counter()
    timings = StepTimings()

    # The discovery call writes speaker_context, so it needs the background first. Wikipedia
    # is cached and fast; the dependency costs less than a second model call would.
    background = await get_author_background(http, settings, req.author_name, req.author_handle, cache)

    t0 = time.perf_counter()
    outcome = await analyzer.discover(req, background, settings.max_claims, prompt_version=prompt_version)
    timings.extract_ms = _ms(t0)
    body = outcome.result

    # Keep only claims whose quote really is in the post, and hand back the exact span so the
    # extension can highlight it. A claim we cannot locate is one we cannot show honestly.
    claims: list[ClaimCandidate] = []
    for draft in body.claims[: settings.max_claims]:
        exact = snap_quote(req.post_text, draft.quote)
        if exact is None:
            continue
        claims.append(ClaimCandidate(id=f"c{len(claims) + 1}", text=draft.text, quote=exact))

    signals = _snap_signals(body.rhetorical_signals, req.post_text)

    return ClaimsResponse(
        claims=claims,
        rhetorical_signals=signals,
        speaker_context=body.speaker_context,
        sources=background,
        transcript=transcript,
        steps=timings,
        latency_ms=_ms(total_started),
        provider=analyzer.name,
        model=outcome.model,
        cost_usd=outcome.cost_usd,
    )


async def check_one_claim(
    req: AnalyzeClaimRequest,
    analyzer: Analyzer,
    http: httpx.AsyncClient,
    settings: Settings,
    prompt_version: str = "v1",
    cache: SearchCache | None = None,
) -> ClaimAnalysisResponse:
    total_started = time.perf_counter()
    timings = StepTimings()
    claim = req.claim

    # Step 2: evidence for this claim only.
    t0 = time.perf_counter()
    evidence = await search_claim(http, settings, MainClaim(found=True, text=claim.text, quote=claim.quote), cache)
    if not evidence:
        # The fake provider carries canned results so every verdict is reachable with no
        # BRAVE_API_KEY. Real providers do not define this and stay at "unverifiable".
        offline = getattr(analyzer, "offline_evidence", None)
        if offline is not None:
            evidence = offline(claim, req.author_handle)
    timings.evidence_ms = _ms(t0)

    # Step 3: verdict on that claim.
    t0 = time.perf_counter()
    outcome = await analyzer.check_claim(req, claim, evidence, prompt_version=prompt_version)
    timings.analyse_ms = _ms(t0)

    check = _cited_only(outcome.result.claim_check, evidence)
    # The reader picked a claim, so "no factual claim" is not an answer this endpoint can give.
    if check.verdict == "no_factual_claim":
        check = check.model_copy(update={"verdict": "unverifiable"})

    return ClaimAnalysisResponse(
        claim=claim,
        claim_check=check,
        missing_context=outcome.result.missing_context,
        evidence=evidence,
        steps=timings,
        latency_ms=_ms(total_started),
        provider=analyzer.name,
        model=outcome.model,
        cost_usd=outcome.cost_usd,
    )
