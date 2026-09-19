#!/usr/bin/env python
"""Walk the two-stage path the extension actually uses, against a running server.

    .venv/bin/python scripts/e2e_twostage.py
    .venv/bin/python scripts/e2e_twostage.py --post spec_example --claim 1

The extension never calls /analyze. content.js asks the service worker for CLAIMS, then for
ANALYZE_CLAIM with the claim the reader picked (extension/content/content.js:106,111 ->
extension/background/background.js:70,75). `make e2e` used to exercise /analyze only, which
left the demo path as the one path nothing tested. This closes that gap.

Two things this checks that a plain 200 would not:

- every stage-1 quote is a literal span of the post, because the drawer renders quotes as
  blockquotes under the claim and stage 2 returns 422 for a quote it cannot locate
  (backend/routers/analyze.py:128-129)
- every cited URL came from the evidence list, which is the citation-grounding guarantee
  `pipeline._cited_only` exists to enforce

The ClaimCandidate from stage 1 is posted back verbatim rather than rebuilt, for the same
reason the extension round-trips it.

Exits non-zero on any HTTP error, any failed check, or when stage 1 finds nothing checkable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.schemas.analysis_schema import VERDICTS  # noqa: E402
from backend.services.text_tools import snap_quote  # noqa: E402
from scripts._render import BAD, INFO, OK, line  # noqa: E402

FIXTURES = json.loads((ROOT / "tests/fixtures/posts.json").read_text())


def post(client: httpx.Client, base: str, path: str, payload: dict, params: dict) -> dict:
    r = client.post(f"{base}{path}", json=payload, params=params, timeout=60.0)
    if r.status_code != 200:
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text
        raise SystemExit(f"[{BAD}] POST {path} -> {r.status_code}: {detail}")
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--post", default="weidel_immigration", help=f"fixture: one of {', '.join(FIXTURES)}")
    ap.add_argument("--claim", type=int, default=0, help="index of the claim to check (default 0)")
    ap.add_argument("--provider", help="override ANALYZER_PROVIDER for this run")
    ap.add_argument("--prompt-version", default="v1", choices=["v0", "v1"])
    args = ap.parse_args()

    if args.post not in FIXTURES:
        line(BAD, f"unknown fixture {args.post!r}; one of {', '.join(FIXTURES)}")
        return 1

    req = FIXTURES[args.post]["request"]
    params = {"prompt_version": args.prompt_version}
    if args.provider:
        params["provider"] = args.provider
    problems: list[str] = []

    with httpx.Client() as client:
        # ---------------------------------------------------------------- stage 1
        stage1 = post(client, args.base, "/api/v1/claims", req, params)
        claims = stage1["claims"]
        line(OK, f"/claims  {len(claims)} claim(s) · {len(stage1['rhetorical_signals'])} signal(s) · "
                 f"{len(stage1['evidence'])} evidence · {stage1['latency_ms']} ms")
        if not claims:
            line(BAD, "stage 1 found nothing checkable, so there is no claim to pick")
            return 1

        for c in claims:
            if snap_quote(req["post_text"], c["quote"]) is None:
                problems.append(f"claim {c['id']} quote is not a span of the post: {c['quote']!r}")
            print(f"    {c['id']}  {c['text']}")

        speaker = stage1["speaker_context"]
        line(INFO, f"speaker  {speaker['name']} · {speaker['background'][:60]}")

        if not 0 <= args.claim < len(claims):
            line(BAD, f"--claim {args.claim} out of range; stage 1 returned {len(claims)}")
            return 1
        picked = claims[args.claim]

        # ---------------------------------------------------------------- stage 2
        stage2 = post(client, args.base, "/api/v1/analyze-claim", {**req, "claim": picked}, params)

    check = stage2["claim_check"]
    line(OK, f"/analyze-claim  {check['verdict']} · {len(check['sources'])} citation(s) · "
             f"{len(stage2['evidence'])} evidence · {stage2['latency_ms']} ms")
    print(f"\n    claim     {picked['text']}")
    print(f"    verdict   {check['verdict'].upper()}")
    print(f"    because   {check['explanation']}")
    print(f"    missing   {stage2['missing_context'] or '(none)'}")
    for s in check["sources"]:
        print(f"    cited     {s['title']} — {s['url']}")

    if check["verdict"] not in VERDICTS:
        problems.append(f"verdict {check['verdict']!r} is outside the taxonomy")
    evidence_urls = {e["url"].rstrip("/") for e in stage2["evidence"]}
    for s in check["sources"]:
        if s["url"].rstrip("/") not in evidence_urls:
            problems.append(f"cited URL was not in the evidence: {s['url']}")

    print()
    for p in problems:
        line(BAD, p)
    if problems:
        return 1
    line(OK, "two-stage path OK — this is what the extension does on a click")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
