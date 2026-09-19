#!/usr/bin/env python
"""Run one post through several arms and print them side by side.

    .venv/bin/python scripts/compare.py --post weidel_immigration
    .venv/bin/python scripts/compare.py --post spec_example --variants nebius:v1,nebius:v0
    .venv/bin/python scripts/compare.py --text "..." --handle someone --name "Some One"
    ANALYZER_PROVIDER=fake .venv/bin/python scripts/compare.py --post spec_example --variants fake:v0,fake:v1

An arm is `provider[/model][:prompt_version[+rigor]]`. Naming the model is how two models of one
provider are compared, which is the comparison this project can actually run: one Nebius key
reaches the whole catalogue, and holding the provider fixed isolates the weights from the
endpoint, the auth and the JSON handling.

    --variants nebius:v1,nebius:v0                      prompts, one model
    --variants nebius:v1,nebius:v1+strict               rigor, one prompt and one model
    --variants nebius/openai/gpt-oss-120b:v1,\
               nebius/Qwen/Qwen3-235B-A22B-Instruct-2507:v1    models, one prompt

Arms run in order, not in parallel, so every arm after the first reuses the cached Brave
evidence: one compare costs one live search, and the arms are judged on the same facts.
Writes the full CompareResponse as JSON. Non-zero exit when every arm failed.
"""

from __future__ import annotations

import argparse
import re
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.config import Settings  # noqa: E402
from backend.main import build_analyzers  # noqa: E402
from backend.schemas.analysis_schema import AnalyzeRequest, CompareResponse, Variant  # noqa: E402
from backend.services.compare import DuplicateLabel, UnknownProvider, run_compare  # noqa: E402
from backend.services.search_cache import NullCache, SearchCache  # noqa: E402
from scripts._render import BAD, INFO, OK, line, render_analysis  # noqa: E402

FIXTURES = json.loads((ROOT / "tests/fixtures/posts.json").read_text())
# gpt-oss-120b against Qwen3-235B: both are in the price table, so the cost row is real, and
# both are instruct models that answer in the token budget. The old default paired nebius with
# gemini, which fails outright whenever GEMINI_API_KEY is unset.
DEFAULT_VARIANTS = "nebius/openai/gpt-oss-120b:v1,nebius/Qwen/Qwen3-235B-A22B-Instruct-2507:v1"


# A tail is a prompt version, optionally carrying a rigor level: v1, v0, v1+strict.
_TAIL = re.compile(r"^(v[01])(?:\+(standard|strict))?$")


def parse_variant(chunk: str) -> Variant:
    """`provider[/model][:prompt_version[+rigor]]` -> one Variant. A bare provider means v1.

    The tail is split off the right, and only when it matches a prompt version exactly.
    That is what lets a model id keep its own slashes and colons: `openai/gpt-oss-120b` is a
    model, and a fine-tune id full of colons stays intact.

    Rigor rides on the version rather than taking a segment of its own, because the two are
    read together -- `v1+strict` is "the guarded prompt, looking harder" -- and because a
    third colon-separated field could not be told apart from a fine-tune id.
    """
    spec, version, rigor = chunk.strip(), "v1", "standard"
    head, sep, tail = spec.rpartition(":")
    if sep and (m := _TAIL.match(tail)):
        spec, version, rigor = head, m.group(1), m.group(2) or "standard"
    provider, _, model = spec.partition("/")
    if not provider:
        raise SystemExit(f"variant {chunk!r} names no provider")
    return Variant(provider=provider, model=model, prompt_version=version, rigor=rigor)


def parse_variants(spec: str) -> list[Variant]:
    """A comma list of variants. At least two, because one arm is not a comparison."""
    out = [parse_variant(c) for c in spec.split(",") if c.strip()]
    if len(out) < 2:
        raise SystemExit(f"need at least two variants, got {spec!r}")
    return out


def summary(result: CompareResponse) -> None:
    def cell(arm, fn) -> str:
        return "FAILED" if arm.response is None else fn(arm)

    def per_arm(fn) -> list[str]:
        return [cell(a, fn) for a in result.arms]

    rows: list[tuple[str, list[str]]] = [
        ("arm", [a.label for a in result.arms]),
        ("verdict", per_arm(lambda x: x.response.analysis.claim_check.verdict)),
        ("claim found", per_arm(lambda x: str(x.response.analysis.main_claim.found))),
        ("signals", per_arm(lambda x: str(len(x.response.analysis.rhetorical_signals)))),
        ("latency", per_arm(lambda x: f"{x.response.latency_ms} ms")),
        ("  claim/evidence/analyse", per_arm(lambda x: f"{x.response.steps.extract_ms}/{x.response.steps.evidence_ms}/{x.response.steps.analyse_ms}")),
        ("cost", per_arm(lambda x: f"${x.response.cost_usd:.5f}" if x.response.cost_usd is not None else "unpriced")),
        ("model", [a.model for a in result.arms]),
        ("warnings", per_arm(lambda x: str(len(x.warnings)))),
    ]

    label_w = max(len(name) for name, _ in rows) + 2
    col_w = max([len(c) for _, cells in rows for c in cells] + [12]) + 2
    ruler = "-" * min(100, label_w + col_w * len(result.arms))

    print("\n" + "=" * len(ruler))
    print("SIDE BY SIDE")
    print("=" * len(ruler))
    for i, (name, cells) in enumerate(rows):
        print(name.ljust(label_w) + "".join(c.ljust(col_w) for c in cells))
        if i == 0:
            print(ruler)

    d = result.diff
    pct = lambda v: "n/a" if v is None else f"{v * 100:.0f}%"  # noqa: E731
    print(ruler)
    print(f"  agreement   claim {pct(d.claim_agreement)} · verdict {pct(d.verdict_agreement)} · signal overlap {pct(d.signal_overlap)}")
    print(f"  total       {result.total_latency_ms} ms · " + (f"${result.total_cost_usd:.5f}" if result.total_cost_usd is not None else "unpriced"))

    for arm in result.arms:
        if arm.error:
            line(BAD, f"{arm.label}: {arm.error}")
        for w in arm.warnings:
            line(INFO, f"{arm.label}: {w}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", help=f"fixture post: one of {', '.join(FIXTURES)}")
    ap.add_argument("--text", help="arbitrary post text instead of a fixture")
    ap.add_argument("--handle", default="example_account", help="author handle, with --text")
    ap.add_argument("--name", default="Example Account", help="author display name, with --text")
    ap.add_argument("--variants", default=DEFAULT_VARIANTS, help=f"comma list of provider[/model][:prompt_version] (default {DEFAULT_VARIANTS})")
    ap.add_argument("--out", help="write the CompareResponse JSON here; default tests/eval/results/compare_<post>_<ts>.json")
    ap.add_argument("--no-blocks", action="store_true", help="only print the side-by-side table")
    args = ap.parse_args()

    if not args.post and not args.text:
        args.post = "weidel_immigration"
    if args.post and args.post not in FIXTURES:
        line(BAD, f"unknown fixture {args.post!r}; one of {', '.join(FIXTURES)}")
        return 1

    if args.post:
        req = AnalyzeRequest(**FIXTURES[args.post]["request"])
        tag = args.post
    else:
        req = AnalyzeRequest(author_handle=args.handle, author_name=args.name, post_text=args.text)
        tag = "adhoc"

    variants = parse_variants(args.variants)
    settings = Settings()  # type: ignore[call-arg]
    analyzers = build_analyzers(settings)
    if not analyzers:
        line(BAD, "no analyzer configured: set NEBIUS_API_KEY or GEMINI_API_KEY, or ANALYZER_PROVIDER=fake")
        return 1
    line(OK, f"providers available: {', '.join(sorted(analyzers))}")
    if not settings.brave_configured:
        line(INFO, "no BRAVE_API_KEY: no evidence will be fetched, so every arm returns 'unverifiable'")

    search_cache = SearchCache(settings.search_cache_path) if settings.search_cache_path else NullCache()
    before = search_cache.live_calls()
    try:
        async with httpx.AsyncClient(follow_redirects=True) as http:
            result = await run_compare(req, variants, analyzers, http, settings, search_cache=search_cache)
        spent = search_cache.live_calls() - before
    except (UnknownProvider, DuplicateLabel) as exc:
        line(BAD, str(exc))
        return 1
    finally:
        search_cache.close()

    if not args.no_blocks:
        for arm in result.arms:
            if arm.response is not None:
                render_analysis(arm.response.analysis, f"{arm.label.upper()} — @{req.author_handle} ({tag}, {arm.model})")

    summary(result)
    line(INFO, f"brave live calls spent: {spent}")

    out = Path(args.out) if args.out else ROOT / "tests/eval/results" / f"compare_{tag}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.model_dump_json(indent=2))
    line(OK, f"written {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")

    if all(arm.error for arm in result.arms):
        line(BAD, "every arm failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
