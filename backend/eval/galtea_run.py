#!/usr/bin/env python
"""Run the real Unfold pipeline against a Galtea version.

    .venv/bin/python -m backend.eval.galtea_run --version version_xxx
    .venv/bin/python -m backend.eval.galtea_run --version version_xxx --status-only

Galtea drives the loop: for every specification linked to the version it resolves the datasets
and test cases, calls the agent below once per case, and evaluates the answer against the
specification's own metrics. This is the opposite direction from ``galtea_sync.py``, which
uploads scores we computed ourselves; here Galtea does the judging.

Two things this file must not do, both from the Galtea agent skill:

- **No ``from __future__ import annotations``.** The SDK chooses the argument shape by comparing
  the first parameter's annotation *by identity*. A stringified annotation falls through to
  ``list[dict]`` silently, so a str-assuming agent would start receiving chat history. Every
  other module in this repo uses that import; this one deliberately does not.
- **Never let the agent raise.** ``evaluations.run`` does not propagate an agent exception. It
  logs it, marks the trace FAILED, and the evaluation ends SKIPPED and unscored. A pipeline
  failure is therefore returned as text so the run stays scoreable and the failure is visible.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load_env_local() -> None:
    """.env.local holds the Galtea key and is git-ignored; it wins over .env."""
    path = ROOT / ".env.local"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_local()

from backend.config import Settings  # noqa: E402
from backend.eval.galtea_sync import render_output  # noqa: E402
from backend.schemas.analysis_schema import AnalyzeRequest  # noqa: E402
from backend.services.nebius_service import NebiusAnalyzer  # noqa: E402
from backend.services.pipeline import run_pipeline  # noqa: E402
from backend.services.search_cache import SearchCache  # noqa: E402

SETTINGS = Settings()  # type: ignore[call-arg]
ANALYZER = None
CACHE = None
HTTP = None
CALLS = {"n": 0, "failed": 0}

# The SDK invokes the agent once per test case and drives an async agent with a fresh event
# loop each time. AsyncOpenAI binds its connection pool to the loop that created it, so from the
# second call on, every other case died with "Event loop is closed" and half the traces were
# rubbish the judge still scored. One loop, owned here, kept open for the whole run, fixes it:
# the agent is therefore SYNCHRONOUS and drives that loop itself.
LOOP = asyncio.new_event_loop()


def parse_post(text):
    """Test case inputs are written as 'Display Name (@handle)\\n\\npost text'.

    Anything that does not match that shape is treated as a bare post with an unknown author,
    which is the safe reading: the pipeline then returns 'Unknown author' rather than inventing
    a speaker, exactly as it should.
    """
    head, sep, body = text.partition("\n\n")
    if sep and "(@" in head and head.endswith(")") and len(head) < 120:
        name, _, handle = head.partition("(@")
        return name.strip(), handle.rstrip(")").strip().lstrip("@"), body.strip()
    return "Unknown", "unknown", text.strip()


def latest_user_message(messages):
    for msg in reversed(messages):
        if msg.get("role") == "user" and msg.get("content"):
            return msg["content"]
    return messages[-1].get("content", "") if messages else ""


async def _analyse(post_text, author_name, author_handle):
    req = AnalyzeRequest(post_text=post_text, author_name=author_name, author_handle=author_handle)
    resp = await run_pipeline(req, ANALYZER, HTTP, SETTINGS, cache=CACHE)
    return render_output(json.loads(resp.model_dump_json()))


def agent(messages: list[dict]) -> str:
    """One test case in, one rendered analysis out."""
    CALLS["n"] += 1
    author_name, author_handle, post_text = parse_post(latest_user_message(messages))
    try:
        answer = LOOP.run_until_complete(_analyse(post_text, author_name, author_handle))
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        CALLS["failed"] += 1
        print(f"  ! agent failed on case {CALLS['n']}: {str(exc)[:160]}", flush=True)
        return f"ANALYSIS FAILED: {type(exc).__name__}: {exc}"
    if CALLS["n"] % 10 == 0:
        print(f"  {CALLS['n']} cases analysed", flush=True)
    return answer


async def _make_http():
    return httpx.AsyncClient(follow_redirects=True)


def report(g, version_id):
    evals = g.evaluations.list(version_id=version_id, limit=500) or []
    by_status = {}
    for e in evals:
        by_status.setdefault(str(getattr(e, "status", "?")).split(".")[-1], []).append(e)
    print(f"\nevaluations for {version_id}: {len(evals)}")
    for status, rows in sorted(by_status.items()):
        scores = [r.score for r in rows if getattr(r, "score", None) is not None]
        mean = f"mean score {sum(scores) / len(scores):.2f}" if scores else "no scores"
        print(f"  {status:<14} {len(rows):>4}   {mean}")
    skipped = by_status.get("SKIPPED", [])
    if skipped:
        print(f"\n  {len(skipped)} SKIPPED — inspect one with: galtea evaluations get {skipped[0].id}")
    return evals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="version_xbptz207dgz2trfdebo0uucp")
    ap.add_argument("--status-only", action="store_true", help="report on a finished run, run nothing")
    args = ap.parse_args()

    if not SETTINGS.galtea_configured:
        print("GALTEA_API_KEY is not set (.env.local or .env)")
        return 1

    from galtea import Galtea

    g = Galtea(api_key=SETTINGS.galtea_api_key, suppress_updatable_version_message=True)
    if args.status_only:
        report(g, args.version)
        return 0

    global ANALYZER, CACHE, HTTP
    asyncio.set_event_loop(LOOP)
    ANALYZER = NebiusAnalyzer(SETTINGS)          # binds AsyncOpenAI to LOOP
    HTTP = LOOP.run_until_complete(_make_http())  # and the httpx pool too
    CACHE = SearchCache(SETTINGS.search_cache_path) if SETTINGS.search_cache_path else None
    brave_before = CACHE.live_calls() if CACHE else 0

    print(f"running {ANALYZER.model} against {args.version}")
    result = g.evaluations.run(version_id=args.version, agent=agent)
    print(f"\nagent calls {CALLS['n']}, failed {CALLS['failed']}")
    if CACHE:
        print(f"brave live calls this run: {CACHE.live_calls() - brave_before}")
    print(f"run returned: {json.dumps(result, indent=2, default=str)[:600]}")

    report(g, args.version)
    print("\nview at https://platform.galtea.ai/")
    LOOP.run_until_complete(HTTP.aclose())
    LOOP.close()
    if CACHE:
        CACHE.close()
    g.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
