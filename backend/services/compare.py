"""Run one post through several provider x model x prompt_version arms and diff the results.

Arms run **sequentially, not concurrently**, on purpose. The Brave cache
(``SearchCache``) is keyed on the normalised claim text, so two arms fired at the same time
would both miss the cache and both spend a live request. Run in order and every arm after the
first reads the identical cached evidence for free, which is what isolates the variable under
test and keeps a compare at one live Brave call. Two arms take about 3 to 8 seconds in total.

A failing arm is recorded and skipped, never raised: one dead provider must not take the
comparison down mid-demo.
"""

from __future__ import annotations

import itertools
import logging
import time

import httpx

from backend.config import Settings
from backend.eval.checks import response_problems
from backend.schemas.analysis_schema import (
    AnalyzeRequest,
    AnalyzeResponse,
    CompareDiff,
    CompareResponse,
    Variant,
    VariantArm,
)
from backend.services.analyzer_base import AnalysisError, Analyzer
from backend.services.cache import TTLCache, make_key
from backend.services.pipeline import run_pipeline
from backend.services.search_cache import SearchCache

log = logging.getLogger(__name__)


class UnknownProvider(ValueError):
    """A variant named a provider that is not configured."""


class DuplicateLabel(ValueError):
    """Two variants resolved to the same label.

    Every diff in CompareDiff is keyed on the label, so duplicates would silently overwrite
    one another and the agreement rates would be computed over a short dict. Cheap to hit by
    naming the same model twice, so it is rejected before anything runs.
    """


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _same_claim(a: AnalyzeResponse, b: AnalyzeResponse) -> bool:
    """Same found flag, and when found, overlapping quoted spans.

    Quote overlap rather than equality: two models routinely pick the same sentence with a
    different number of leading words, which is agreement for our purposes.
    """
    ca, cb = a.analysis.main_claim, b.analysis.main_claim
    if ca.found != cb.found:
        return False
    if not ca.found:
        return True
    qa, qb = ca.quote.strip().lower(), cb.quote.strip().lower()
    if not qa or not qb:
        return ca.text.strip().lower() == cb.text.strip().lower()
    return qa in qb or qb in qa


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def build_diff(arms: list[VariantArm]) -> CompareDiff:
    diff = CompareDiff()
    for arm in arms:
        if arm.response is None:
            continue
        diff.verdicts[arm.label] = arm.response.analysis.claim_check.verdict
        diff.signals[arm.label] = [s.name for s in arm.response.analysis.rhetorical_signals]
        diff.latency_ms[arm.label] = arm.response.latency_ms
        diff.cost_usd[arm.label] = arm.response.cost_usd

    ok = [a for a in arms if a.response is not None]
    if len(ok) < 2:
        return diff

    claim_hits, verdict_hits, overlaps = [], [], []
    for x, y in itertools.combinations(ok, 2):
        assert x.response is not None and y.response is not None  # narrowed by the filter above
        claim_hits.append(1.0 if _same_claim(x.response, y.response) else 0.0)
        verdict_hits.append(
            1.0 if x.response.analysis.claim_check.verdict == y.response.analysis.claim_check.verdict else 0.0
        )
        overlaps.append(_jaccard(set(diff.signals[x.label]), set(diff.signals[y.label])))

    diff.claim_agreement = _mean(claim_hits)
    diff.verdict_agreement = _mean(verdict_hits)
    diff.signal_overlap = _mean(overlaps)
    return diff


async def run_compare(
    req: AnalyzeRequest,
    variants: list[Variant],
    analyzers: dict[str, Analyzer],
    http: httpx.AsyncClient,
    settings: Settings,
    search_cache: SearchCache | None = None,
    cache: TTLCache[AnalyzeResponse] | None = None,
    variant_analyzers: dict[tuple[str, str], Analyzer] | None = None,
) -> CompareResponse:
    """One arm per variant, in order. Validates every variant before running anything.

    `variant_analyzers` memoises the per-model analyzers across calls. It matters for Nebius,
    which remembers per model whether strict json_schema was rejected: rebuilding the analyzer
    every request would forget that and re-pay the downgrade round trip on each compare.
    """
    missing = sorted({v.provider for v in variants} - set(analyzers))
    if missing:
        raise UnknownProvider(f"unknown or unconfigured provider(s): {', '.join(missing)}. Available: {sorted(analyzers)}")

    labels = [v.resolved_label() for v in variants]
    dupes = sorted({x for x in labels if labels.count(x) > 1})
    if dupes:
        raise DuplicateLabel(f"two variants resolve to the same label: {', '.join(dupes)}. Give one an explicit label.")

    if variant_analyzers is None:
        variant_analyzers = {}

    started = time.perf_counter()
    arms: list[VariantArm] = []

    for variant in variants:
        analyzer = analyzers[variant.provider]
        if variant.model:
            key_a = (variant.provider, variant.model)
            if key_a not in variant_analyzers:
                variant_analyzers[key_a] = analyzer.with_model(variant.model)
            analyzer = variant_analyzers[key_a]
        arm = VariantArm(
            label=variant.resolved_label(),
            provider=variant.provider,
            prompt_version=variant.prompt_version,
            rigor=variant.rigor,
            model=analyzer.model,
        )
        # Same key shape as routers/analyze.py, so a compare and a plain analyze share hits.
        key = make_key(f"{analyzer.name}:{analyzer.model}:{variant.prompt_version}{'' if variant.rigor == 'standard' else ':' + variant.rigor}:{req.author_handle}", req.post_text)
        hit = cache.get(key) if cache is not None else None
        if hit is not None:
            arm.response = hit.model_copy(update={"cached": True})
        else:
            try:
                resp = await run_pipeline(
                    req, analyzer, http, settings, variant.prompt_version, variant.rigor, cache=search_cache
                )
            except AnalysisError as exc:
                log.warning("compare arm %s failed: %s", arm.label, exc)
                arm.error = str(exc)
                arms.append(arm)
                continue
            if cache is not None:
                cache.set(key, resp)
            arm.response = resp
        arm.warnings = response_problems(arm.response, req.post_text)
        arms.append(arm)

    costs = [a.response.cost_usd for a in arms if a.response is not None and a.response.cost_usd is not None]
    first_ok = next((a.response for a in arms if a.response is not None), None)

    return CompareResponse(
        post_text=req.post_text,
        author_handle=req.author_handle,
        arms=arms,
        diff=build_diff(arms),
        evidence=first_ok.evidence if first_ok else [],
        sources=first_ok.sources if first_ok else [],
        total_latency_ms=int((time.perf_counter() - started) * 1000),
        total_cost_usd=sum(costs) if costs else None,
    )
