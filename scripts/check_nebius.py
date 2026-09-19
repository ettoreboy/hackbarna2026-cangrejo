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
from backend.eval.checks import response_problems  # noqa: E402
from backend.schemas.analysis_schema import AnalyzeRequest  # noqa: E402
from backend.services.analyzer_base import AnalysisError  # noqa: E402
from backend.services.nebius_service import NebiusAnalyzer  # noqa: E402
from backend.services.pipeline import run_pipeline  # noqa: E402
from backend.services.pricing import NEBIUS_PRICES  # noqa: E402
from scripts._render import BAD, INFO, OK, line, render_analysis, render_timings  # noqa: E402

FIXTURES = json.loads((ROOT / "tests/fixtures/posts.json").read_text())


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

    render_analysis(resp.analysis, f"POST ANALYSIS — @{req.author_handle} ({args.post}, prompt {args.prompt_version})")
    render_timings(resp, elapsed_ms)

    problems = response_problems(resp, req.post_text)
    for p in problems:
        line(INFO, p)

    print()
    if problems:
        line(BAD, f"{len(problems)} check(s) failed")
        return 1
    line(OK, "all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
