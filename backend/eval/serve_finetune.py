#!/usr/bin/env python
"""Serve a fine-tuned checkpoint on a Nebius dedicated endpoint, then smoke-test it.

    .venv/bin/python -m backend.eval.serve_finetune --dry-run   # print the request, create nothing
    .venv/bin/python -m backend.eval.serve_finetune             # create, wait, smoke-test
    .venv/bin/python -m backend.eval.serve_finetune --list
    .venv/bin/python -m backend.eval.serve_finetune --delete <endpoint_id>

A LoRA fine-tune is NOT callable on the shared inference API: the job's `fine_tuned_model` is
null and the checkpoint ids carry literal `org_placeholder` text. Every attempt to use one as a
model name returns 404.

BLOCKED, as of 19 Sep 2026. A dedicated endpoint takes `custom_weights_id`, which must start
with `model-artifact_`. Model artifacts are created at POST /v0/model_artifacts, which accepts
`kind: "full"` only (not `lora`) and exactly one source, `{"huggingface": {"repo_id": ...}}`.
There is no way to point either resource at a Token Factory fine-tuning checkpoint. Serving our
adapter would mean merging it into the 30B base, pushing ~60 GB to Hugging Face and registering
that repo — not a hackathon-scale task. GET /v0/model_artifacts also returns 403 on this
account, so the beta may not be enabled either.

This script is kept because the shape is right and one mentor answer may unblock it.

CREATING AN ENDPOINT STARTS A GPU AND BILLS BY THE HOUR. Delete it when the demo is done.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402

STATE = ROOT / "tests/eval/results/finetune.json"
API = "https://api.tokenfactory.nebius.com/v0/dedicated_endpoints"


def best_checkpoint() -> tuple[str, str]:
    """(checkpoint id, base model) for the lowest validation loss in the saved job state."""
    state = json.loads(STATE.read_text())
    cps = state.get("checkpoints") or []
    if not cps:
        raise SystemExit(f"no checkpoints in {STATE.relative_to(ROOT)}; run the fine-tune first")
    best = min(cps, key=lambda c: (c["metrics"].get("valid_loss") is None, c["metrics"].get("valid_loss", 9e9)))
    print(f"checkpoint {best['id']}  step {best['step_number']}  valid_loss {best['metrics']['valid_loss']:.4f}")
    return best["id"], state["model"]


async def wait_running(client: httpx.AsyncClient, headers: dict, endpoint_id: str, every: int) -> dict:
    while True:
        r = await client.get(f"{API}", headers=headers)
        r.raise_for_status()
        me = next((e for e in r.json()["data"] if e.get("id") == endpoint_id), None)
        if me is None:
            raise SystemExit(f"endpoint {endpoint_id} disappeared")
        status = me.get("status") or me.get("state")
        print(f"  status={status}", flush=True)
        if str(status).lower() in ("running", "active", "ready"):
            return me
        if str(status).lower() in ("failed", "error", "deleted"):
            raise SystemExit(f"endpoint ended in {status}: {json.dumps(me)[:300]}")
        await asyncio.sleep(every)


async def smoke(settings: Settings, model: str) -> None:
    """One real pipeline post through the served model, so we learn latency and whether the
    strict schema survives fine-tuning."""
    from backend.schemas.analysis_schema import AnalyzeRequest
    from backend.services.nebius_service import NebiusAnalyzer
    from backend.services.pipeline import run_pipeline
    from backend.services.search_cache import SearchCache

    tuned = settings.model_copy(update={"nebius_model": model})
    analyzer = NebiusAnalyzer(tuned)
    req = AnalyzeRequest(
        post_text="Germany accepted 1.2M migrants last year. This government clearly doesn't care about German citizens.",
        author_name="Test Account", author_handle="test",
    )
    cache = SearchCache(tuned.search_cache_path)
    started = time.perf_counter()
    async with httpx.AsyncClient(follow_redirects=True) as http:
        resp = await run_pipeline(req, analyzer, http, tuned, cache=cache)
    took = time.perf_counter() - started
    a = resp.analysis
    print(f"\n  {took:.1f} s end to end")
    print(f"  verdict  {a.claim_check.verdict} — {a.claim_check.explanation[:120]}")
    print(f"  signals  {[s.name for s in a.rhetorical_signals]}")
    print(f"  speaker  {a.speaker_context.background[:80]}")
    cache.close()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="contextguard-v3")
    ap.add_argument("--gpu-type", default="gpu-h200-sxm")
    ap.add_argument("--region", default="us-central1")
    ap.add_argument("--gpu-count", type=int, default=1)
    ap.add_argument("--flavor", default="base")
    ap.add_argument("--poll", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--delete", metavar="ENDPOINT_ID")
    ap.add_argument("--no-smoke", action="store_true")
    args = ap.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    headers = {"Authorization": f"Bearer {settings.nebius_api_key}"}

    async with httpx.AsyncClient(timeout=60) as client:
        if args.list:
            r = await client.get(API, headers=headers)
            print(json.dumps(r.json(), indent=2))
            return 0
        if args.delete:
            r = await client.delete(f"{API}/{args.delete}", headers=headers)
            print(r.status_code, r.text[:300])
            return 0 if r.is_success else 1

        ckpt_id, base_model = best_checkpoint()
        body = {
            "name": args.name,
            "description": "ContextGuard step-3 analyser, LoRA on 194 self-consistent examples",
            "model_name": base_model,
            "flavor_name": args.flavor,
            "gpu_type": args.gpu_type,
            "region": args.region,
            "gpu_count": args.gpu_count,
            "custom_weights_id": ckpt_id,
            "scaling": {"min_replicas": 1, "max_replicas": 1},
        }
        print(json.dumps(body, indent=2))
        if args.dry_run:
            print("\ndry run: nothing created. This would start a billed GPU.")
            return 0

        r = await client.post(API, headers=headers, json=body)
        if not r.is_success:
            print(f"create failed {r.status_code}: {r.text[:500]}")
            return 1
        ep = r.json()
        endpoint_id = ep.get("id")
        print(f"created endpoint {endpoint_id}")
        state = json.loads(STATE.read_text())
        state["endpoint"] = ep
        STATE.write_text(json.dumps(state, indent=2, default=str))

        ep = await wait_running(client, headers, endpoint_id, args.poll)
        state["endpoint"] = ep
        STATE.write_text(json.dumps(state, indent=2, default=str))
        served = ep.get("routing_key") or ep.get("model_name") or endpoint_id
        print(f"\nserved as: {served}")
        print(f"delete with: .venv/bin/python -m backend.eval.serve_finetune --delete {endpoint_id}")

    if not args.no_smoke:
        await smoke(settings, served)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
