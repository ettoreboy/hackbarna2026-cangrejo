#!/usr/bin/env python
"""Validate a Nebius key and the whole claim-first pipeline. Run it after any prompt change.

    .venv/bin/python scripts/check_nebius.py
    .venv/bin/python scripts/check_nebius.py --post spec_example
    .venv/bin/python scripts/check_nebius.py --model Qwen/Qwen3-235B-A22B-Instruct-2507
    .venv/bin/python scripts/check_nebius.py --list-models

Checks the key, the model, strict structured output, and both pipeline steps, then prints the
five blocks the client renders plus per-step latency and cost. Non-zero exit on any failure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.config import Settings  # noqa: E402
from backend.schemas.analysis_schema import AnalyzeRequest  # noqa: E402
from backend.services.analyzer_base import AnalysisError  # noqa: E402
from backend.services.nebius_service import NebiusAnalyzer  # noqa: E402
from backend.services.pipeline import run_pipeline  # noqa: E402
from backend.services.pricing import NEBIUS_PRICES  # noqa: E402

OK, BAD, INFO = "  ok  ", " FAIL ", " .... "
FIXTURES = json.loads((ROOT / "tests/fixtures/posts.json").read_text())


def line(mark: str, text: str) -> None:
    print(f"[{mark}] {text}", flush=True)


def block(title: str, body: str) -> None:
    print(f"\n{title}\n{body}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="override NEBIUS_MODEL")
    ap.add_argument("--fast-model", help="override NEBIUS_FAST_MODEL (claim extraction)")
    ap.add_argument("--post", default="weidel_immigration", help=f"one of {', '.join(FIXTURES)}")
    ap.add_argument("--prompt-version", default="v1", choices=["v0", "v1"])
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    update = {}
    if args.model:
        update["nebius_model"] = args.model
    if args.fast_model:
        update["nebius_fast_model"] = args.fast_model
    if update:
        settings = settings.model_copy(update=update)

    if not settings.nebius_configured:
        line(BAD, "NEBIUS_API_KEY is not set. Put it in .env and re-run.")
        return 1

    try:
        analyzer = NebiusAnalyzer(settings)
    except AnalysisError as exc:
        line(BAD, str(exc))
        return 1

    try:
        ids = sorted(m.id for m in (await analyzer.client.models.list()).data)
    except Exception as exc:
        line(BAD, f"could not list models: {exc}")
        return 1
    line(OK, f"authenticated, {len(ids)} models reachable")

    if args.list_models:
        for mid in ids:
            price = NEBIUS_PRICES.get(mid)
            print(f"    {mid}" + (f"  ${price[0]}/${price[1]} per 1M" if price else ""))
        return 0

    for label, model in (("analysis", analyzer.model), ("claim extraction", analyzer.fast_model)):
        if model not in ids:
            line(BAD, f"{label} model {model} is not in the catalogue")
            return 1
    line(OK, f"models available: {analyzer.fast_model} (step 1), {analyzer.model} (step 3)")
    if analyzer.reasoning_effort:
        line(INFO, f"reasoning_effort={analyzer.reasoning_effort}")
    if not settings.brave_configured:
        line(INFO, "no BRAVE_API_KEY: no evidence will be fetched, so the verdict will be 'unverifiable'")

    req = AnalyzeRequest(**FIXTURES[args.post]["request"])
    started = time.perf_counter()
    async with httpx.AsyncClient(follow_redirects=True) as http:
        try:
            resp = await run_pipeline(req, analyzer, http, settings, prompt_version=args.prompt_version)
        except AnalysisError as exc:
            line(BAD, f"pipeline failed: {exc}")
            return 1
    elapsed_ms = (time.perf_counter() - started) * 1000

    mode = "strict json_schema" if all(analyzer._strict_ok.get(m, True) for m in (analyzer.model, analyzer.fast_model)) else "json_object fallback"
    line(OK, f"pipeline completed via {mode}")

    a = resp.analysis
    print("\n" + "=" * 68)
    print(f"POST ANALYSIS — @{req.author_handle} ({args.post}, prompt {args.prompt_version})")
    print("=" * 68)
    if a.main_claim.found:
        block("MAIN CLAIM", f'  "{a.main_claim.text}"\n  quoted: "{a.main_claim.quote}"')
    else:
        block("MAIN CLAIM", "  none found (no checkable factual claim)")
    src = "\n".join(f"  - {s.title} — {s.url}" for s in a.claim_check.sources) or "  (none cited)"
    block("CLAIM CHECK", f"  {a.claim_check.verdict.upper()}\n  {a.claim_check.explanation}\n  Sources:\n{src}")
    block("MISSING CONTEXT", f"  {a.missing_context or '(none)'}")
    sig = "\n".join(f'  [{s.name}]  "{s.evidence}"' for s in a.rhetorical_signals) or "  (none)"
    block("RHETORICAL SIGNALS", sig)
    sp = a.speaker_context
    block("SPEAKER CONTEXT", f"  {sp.name}" + (f" · {sp.role}" if sp.role else "") + f"\n  {sp.background}")

    cost = f"${resp.cost_usd:.5f}" if resp.cost_usd is not None else "unpriced"
    print(f"\n    total {elapsed_ms:.0f} ms  =  claim {resp.steps.extract_ms} + evidence {resp.steps.evidence_ms} + analysis {resp.steps.analyse_ms}")
    print(f"    cost {cost} · evidence {len(resp.evidence)} results · background {len(resp.sources)} sources")

    problems = []
    if a.main_claim.found and a.main_claim.quote and a.main_claim.quote not in req.post_text:
        problems.append("claim quote is not verbatim from the post")
    for s in a.rhetorical_signals:
        if s.evidence and s.evidence not in req.post_text:
            problems.append(f"signal {s.name} quote is not verbatim")
        if s.name.startswith("Other: "):
            problems.append(f"label outside the taxonomy: {s.name}")
    evidence_urls = {e.url.rstrip('/') for e in resp.evidence}
    for c in a.claim_check.sources:
        if c.url.rstrip("/") not in evidence_urls:
            problems.append(f"cited URL was not in the evidence: {c.url}")
    for p in problems:
        line(INFO, p)

    print()
    line(OK, "all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
