#!/usr/bin/env python
"""Validate a Nebius Token Factory key end to end. Run this the moment the key arrives.

    .venv/bin/python scripts/check_nebius.py
    .venv/bin/python scripts/check_nebius.py --model openai/gpt-oss-120b
    .venv/bin/python scripts/check_nebius.py --list-models

Checks, in order:
  1. the key authenticates and models can be listed
  2. the configured model exists
  3. strict json_schema structured output works on it
  4. one real analysis of the benchmark post parses into the schema
  5. reports latency, tokens and cost

Exit code is non-zero if any check fails, so it can gate the eval runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import Settings  # noqa: E402
from backend.schemas.analysis_schema import AnalyzeRequest, Source  # noqa: E402
from backend.services.analyzer_base import AnalysisError  # noqa: E402
from backend.services.nebius_service import NebiusAnalyzer  # noqa: E402
from backend.services.pricing import NEBIUS_PRICES  # noqa: E402

OK, BAD, INFO = "  ok  ", " FAIL ", " .... "
FIXTURES = json.loads((Path(__file__).resolve().parent.parent / "tests/fixtures/posts.json").read_text())


def line(mark: str, text: str) -> None:
    print(f"[{mark}] {text}", flush=True)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="override NEBIUS_MODEL for this run")
    ap.add_argument("--list-models", action="store_true", help="print every model id the key can reach, then exit")
    ap.add_argument("--fixture", default="weidel_immigration", help="which fixture post to analyse")
    args = ap.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    if args.model:
        settings = settings.model_copy(update={"nebius_model": args.model})

    if not settings.nebius_configured:
        line(BAD, "NEBIUS_API_KEY is not set. Put it in .env and re-run.")
        return 1
    line(OK, f"key present, base_url {settings.nebius_base_url}")

    try:
        analyzer = NebiusAnalyzer(settings)
    except AnalysisError as exc:
        line(BAD, str(exc))
        return 1

    # 1. auth + model catalogue
    try:
        listing = await analyzer.client.models.list()
        ids = sorted(m.id for m in listing.data)
    except Exception as exc:
        line(BAD, f"could not list models: {exc}")
        return 1
    line(OK, f"authenticated, {len(ids)} models reachable")

    if args.list_models:
        for mid in ids:
            price = NEBIUS_PRICES.get(mid)
            tag = f"  ${price[0]}/${price[1]} per 1M" if price else ""
            print(f"    {mid}{tag}")
        return 0

    # 2. configured model present
    if settings.nebius_model in ids:
        line(OK, f"model {settings.nebius_model} is available")
    else:
        line(BAD, f"model {settings.nebius_model} not in the catalogue")
        near = [m for m in ids if m.split("/")[-1][:6].lower() in settings.nebius_model.lower()][:8]
        if near:
            print("    closest ids:", ", ".join(near))
        return 1

    if settings.nebius_model not in NEBIUS_PRICES:
        line(
            INFO,
            f"no price for {settings.nebius_model}; cost column will be empty. "
            "Set NEBIUS_PRICES to fill it (see backend/services/pricing.py).",
        )

    # 3 + 4. a real structured analysis
    req = AnalyzeRequest(**FIXTURES[args.fixture]["request"])
    sources = [
        Source(
            title="Alice Weidel",
            url="https://en.wikipedia.org/wiki/Alice_Weidel",
            snippet="Alice Weidel is a German politician and co-leader of the AfD.",
            provider="wikipedia",
        )
    ]
    started = time.perf_counter()
    try:
        outcome = await analyzer.analyze(req, sources)
    except AnalysisError as exc:
        line(BAD, f"analysis failed: {exc}")
        return 1
    elapsed_ms = (time.perf_counter() - started) * 1000

    mode = "strict json_schema" if analyzer._use_strict else "json_object fallback"
    line(OK, f"structured output works via {mode}")

    a = outcome.result
    cost = f"${outcome.cost_usd:.5f}" if outcome.cost_usd is not None else "unpriced"
    line(OK, f"analysis parsed: band={a.score_band} score={a.manipulation_score}")
    print(f"\n    latency   {elapsed_ms:.0f} ms")
    print(f"    tokens    {outcome.prompt_tokens} in / {outcome.completion_tokens} out")
    print(f"    cost      {cost}")
    print(f"\n    summary   {a.post_summary}")
    print(f"    author    {a.author_background[:120]}")
    print(f"    signals   {', '.join(f'{s.name} ({s.confidence:.2f})' for s in a.communication_signals) or 'none'}")
    print(f"    fallacies {', '.join(f.name for f in a.logical_fallacies) or 'none'}")
    print(f"    intent    {a.indicators.strategic_intent}")
    print(f"    timing    {a.indicators.timing_note}")
    print(f"    lesson    {a.cognitive_summary[:160]}")

    uncited = [s.name for s in a.communication_signals if not s.evidence.strip()]
    if uncited:
        line(INFO, f"signals with no quoted evidence: {uncited}")
    off_list = [s.name for s in a.communication_signals if s.name.startswith("Other: ")]
    if off_list:
        line(INFO, f"labels outside the taxonomy: {off_list}")

    print()
    line(OK, "all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
