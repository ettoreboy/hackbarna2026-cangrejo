#!/usr/bin/env python
"""Build a knowledge base for Galtea from evidence the pipeline actually retrieved.

    .venv/bin/python -m backend.eval.make_kb

ContextGuard has no fixed corpus: it is an open-web checker, and the documents it works with are
the search results it fetches per post. Galtea's accuracy flow wants a knowledge base so it can
generate test cases and know where the correct answer came from. The honest equivalent is the
evidence our own runs retrieved and the verdicts they supported, so that is what this writes:
one Markdown file per post, with the claim, the sources and the verdict grounded in them.

Reads existing result files only. No model and no search calls.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT_RUNS = [
    "tests/eval/results/nebius_openai-gpt-oss-120b_v1.json",
    "tests/eval/results/tweets_nebius_openai-gpt-oss-120b_v1.json",
]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "post"


def document(item: dict, rec: dict) -> str:
    a = rec["analysis"]
    claim, check = a["main_claim"], a["claim_check"]
    out = [
        f"# {item['id']}",
        "",
        f"**Post** by {item['author_name']} (@{item['author_handle']})",
        "",
        f"> {item['post_text']}",
        "",
        "## Claim under check",
        "",
        claim["text"] if claim["found"] else "_The post makes no checkable factual claim._",
        "",
        "## Verdict grounded in the sources below",
        "",
        f"**{check['verdict']}** — {check['explanation']}",
        "",
        "## What the post leaves out",
        "",
        a["missing_context"] or "_Nothing recorded._",
        "",
        "## Sources retrieved for this post",
        "",
    ]
    evidence = rec.get("evidence") or []
    if not evidence:
        out.append("_No web evidence was retrieved, so the claim could not be checked._")
    for e in evidence:
        out += [f"### {e['title']}", "", e["url"], "", e.get("snippet") or "", ""]
    background = rec.get("sources") or []
    if background:
        out += ["## Who the author is", ""]
        for s in background:
            out += [f"### {s['title']}", "", s["url"], "", s.get("snippet") or "", ""]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*", default=DEFAULT_RUNS)
    ap.add_argument("--out", default="tests/eval/galtea_knowledge_base.zip")
    args = ap.parse_args()

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for run in args.runs:
            path = ROOT / run
            if not path.exists():
                print(f"  ! missing {run}")
                continue
            payload = json.loads(path.read_text())
            items = {i["id"]: i for i in payload["items"]}
            for rec in payload["records"]:
                if rec.get("error") or rec["id"] not in items:
                    skipped += 1
                    continue
                item = items[rec["id"]]
                # A post with no retrieved evidence teaches Galtea nothing about where a correct
                # answer comes from, so it is left out of the knowledge base.
                if not rec.get("evidence") and not rec.get("sources"):
                    skipped += 1
                    continue
                z.writestr(f"{path.stem}/{_slug(rec['id'])}.md", document(item, rec))
                written += 1
    print(f"{written} documents written, {skipped} skipped (no retrieved evidence)")
    print(f"{out.relative_to(ROOT)}  {out.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
