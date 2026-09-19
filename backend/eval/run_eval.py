#!/usr/bin/env python
"""Run the pipeline over the eval set and score it.

    .venv/bin/python -m backend.eval.run_eval --prompt-version v1
    .venv/bin/python -m backend.eval.run_eval --prompt-version v0 --model Qwen/Qwen3-235B-A22B-Instruct-2507
    .venv/bin/python -m backend.eval.run_eval --score-only tests/eval/results/nebius_gpt-oss-120b_v1.json

Brave results come from the disk cache, so a second run over the same set costs nothing.
Use --no-evidence to skip search entirely while iterating on prompts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.eval.dataset import load_eval_set  # noqa: E402
from backend.eval.metrics import score_run  # noqa: E402
from backend.services.analyzer_base import AnalysisError  # noqa: E402
from backend.services.nebius_service import NebiusAnalyzer  # noqa: E402
from backend.services.pipeline import run_pipeline  # noqa: E402
from backend.services.search_cache import NullCache, SearchCache  # noqa: E402


def build_analyzer(settings: Settings, provider: str):
    if provider == "nebius":
        return NebiusAnalyzer(settings)
    if provider == "gemini":
        from backend.services.gemini_service import GeminiAnalyzer

        return GeminiAnalyzer(settings)
    if provider == "fake":
        from backend.services.fake_service import FakeAnalyzer

        return FakeAnalyzer()
    raise SystemExit(f"unknown provider {provider}")


async def run_one(item, analyzer, http, settings, cache, prompt_version, sem) -> dict:
    async with sem:
        started = time.perf_counter()
        try:
            from backend.schemas.analysis_schema import AnalyzeRequest

            resp = await run_pipeline(
                AnalyzeRequest(**item.to_request()), analyzer, http, settings,
                prompt_version=prompt_version, cache=cache,
            )
        except AnalysisError as exc:
            return {"id": item.id, "group": item.group, "error": str(exc)}
        rec = json.loads(resp.model_dump_json())
        rec["id"] = item.id
        rec["group"] = item.group
        rec["wall_ms"] = int((time.perf_counter() - started) * 1000)
        # The server drops invented URLs before we see them; keep what the model asked for.
        rec["raw_cited_urls"] = [s["url"] for s in rec["analysis"]["claim_check"]["sources"]]
        return rec


def report(results, records, args) -> None:
    ok = [r for r in records if not r.get("error")]
    errs = [r for r in records if r.get("error")]
    print("\n" + "=" * 74)
    print(f"{args.provider} · {args.model_label} · prompt {args.prompt_version} · {len(ok)}/{len(records)} ok")
    print("=" * 74)
    for m in results:
        print(f"  {m.name:<22} {m.display:>5}   n={m.n:<4} {m.detail}")
    if ok:
        lat = sorted(r["wall_ms"] for r in ok)
        costs = [r["cost_usd"] for r in ok if r.get("cost_usd") is not None]
        print(f"\n  median latency  {statistics.median(lat):.0f} ms      p90 {lat[int(len(lat) * 0.9) - 1]:.0f} ms")
        if costs:
            print(f"  cost per post   ${statistics.mean(costs):.5f}      per 1000 posts ${statistics.mean(costs) * 1000:.2f}")
        verdicts: dict[str, int] = {}
        for r in ok:
            v = r["analysis"]["claim_check"]["verdict"]
            verdicts[v] = verdicts.get(v, 0) + 1
        print(f"  verdicts        {json.dumps(verdicts)}")
    for m in results:
        if m.failures:
            print(f"\n  {m.name} misses:")
            for f in m.failures[:8]:
                print(f"    - {f}")
    for e in errs[:5]:
        print(f"\n  ERROR {e['id']}: {e['error'][:120]}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="tests/eval/eval_set.jsonl")
    ap.add_argument("--provider", default="nebius", choices=["nebius", "gemini", "fake"])
    ap.add_argument("--model", help="override the provider's model")
    ap.add_argument("--prompt-version", default="v1", choices=["v0", "v1"])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, help="only the first N items, for a smoke run")
    ap.add_argument("--no-evidence", action="store_true", help="skip Brave entirely")
    ap.add_argument("--out", help="results path; default tests/eval/results/<provider>_<model>_<prompt>.json")
    ap.add_argument("--score-only", help="re-score an existing results file without calling any model")
    args = ap.parse_args()

    items = load_eval_set(ROOT / args.set)
    if args.limit:
        items = items[: args.limit]
    items_raw = [i.model_dump() for i in items]

    if args.score_only:
        payload = json.loads(Path(args.score_only).read_text())
        records = payload["records"]
        args.provider, args.model_label = payload["provider"], payload["model"]
        args.prompt_version = payload["prompt_version"]
        report(score_run(records, payload["items"]), records, args)
        return 0

    settings = Settings()  # type: ignore[call-arg]
    if args.model:
        settings = settings.model_copy(update={"nebius_model": args.model} if args.provider == "nebius" else {"gemini_model": args.model})
    if args.no_evidence:
        settings = settings.model_copy(update={"brave_api_key": ""})

    analyzer = build_analyzer(settings, args.provider)
    args.model_label = getattr(analyzer, "model", args.provider)
    cache = SearchCache(settings.search_cache_path) if settings.search_cache_path else NullCache()
    before = cache.live_calls()

    print(f"running {len(items)} posts · {args.provider}/{args.model_label} · prompt {args.prompt_version} · evidence {'off' if args.no_evidence else 'on'}", flush=True)
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(follow_redirects=True) as http:
        records = await asyncio.gather(*(run_one(i, analyzer, http, settings, cache, args.prompt_version, sem) for i in items))

    spent = cache.live_calls() - before
    set_tag = Path(args.set).stem
    out = Path(args.out) if args.out else ROOT / f"tests/eval/results/{set_tag}_{args.provider}_{args.model_label.replace('/', '-')}_{args.prompt_version}.json"
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "provider": args.provider, "model": args.model_label, "prompt_version": args.prompt_version,
        "brave_live_calls": spent, "items": items_raw, "records": list(records),
    }, indent=2))

    results = score_run(list(records), items_raw)
    report(results, list(records), args)
    print(f"\n  brave live calls this run: {spent} (total spent {cache.live_calls()})")
    print(f"  written to {out}")
    cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
