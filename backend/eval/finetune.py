#!/usr/bin/env python
"""Upload the fine-tune files and run a LoRA job on Nebius Token Factory.

    .venv/bin/python -m backend.eval.finetune                 # upload, create, poll until done
    .venv/bin/python -m backend.eval.finetune --no-wait       # create and exit
    .venv/bin/python -m backend.eval.finetune --status ftjob-xxxx
    .venv/bin/python -m backend.eval.finetune --dry-run       # validate files, print the request, create nothing

State is written to tests/eval/results/finetune.json after every step so a crash or Ctrl-C
loses nothing; re-running with --status picks up from the job id.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402

STATE = ROOT / "tests/eval/results/finetune.json"
TERMINAL = {"succeeded", "failed", "cancelled"}


def validate_jsonl(path: Path) -> tuple[int, int]:
    """Return (examples, approx_tokens). Raises on a malformed line."""
    n, chars = 0, 0
    with path.open() as fh:
        for i, line in enumerate(fh, 1):
            row = json.loads(line)
            msgs = row["messages"]
            assert [m["role"] for m in msgs] == ["system", "user", "assistant"], f"line {i}: roles"
            json.loads(msgs[2]["content"])  # assistant turn must itself be valid JSON
            chars += sum(len(m["content"]) for m in msgs)
            n += 1
    return n, chars // 4


def save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, default=str))


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


async def poll(client: AsyncOpenAI, job_id: str, state: dict, every: int) -> dict:
    seen_events: set[str] = set()
    while True:
        job = await client.fine_tuning.jobs.retrieve(job_id)
        state["job"] = job.model_dump()
        try:
            events = await client.fine_tuning.jobs.list_events(job_id, limit=50)
            for ev in reversed(events.data):
                if ev.id in seen_events:
                    continue
                seen_events.add(ev.id)
                state.setdefault("events", []).append(ev.model_dump())
                print(f"  {time.strftime('%H:%M:%S')}  {ev.message}")
        except Exception as exc:  # events endpoint is optional
            state["events_error"] = str(exc)[:200]
        save(state)
        if job.status in TERMINAL:
            return state
        print(f"  status={job.status}  trained_tokens={getattr(job, 'trained_tokens', None)}", flush=True)
        await asyncio.sleep(every)


async def save_checkpoints(client: AsyncOpenAI, job_id: str, state: dict) -> None:
    """The loss curve lives on the checkpoints endpoint, not on the job. Without this the
    only record of how training went is lost when the process exits."""
    try:
        cps = await client.fine_tuning.jobs.checkpoints.list(job_id)
    except Exception as exc:
        print(f"could not list checkpoints: {str(exc)[:120]}")
        return
    state["checkpoints"] = [c.model_dump() for c in cps.data]
    save(state)
    for c in sorted(cps.data, key=lambda x: x.step_number or 0):
        m = c.metrics
        print(f"  step {c.step_number:>3}  train_loss {m.train_loss:.4f}  valid_loss {m.valid_loss:.4f}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="tests/eval/ft_train.jsonl")
    ap.add_argument("--valid", default="tests/eval/ft_valid.jsonl")
    ap.add_argument("--model", default="Qwen/Qwen3-30B-A3B-Instruct-2507")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--batch-size", type=int, default=16,
                    help="Nebius requires batch_size * 8192 >= 131072, so 16 is the minimum")
    ap.add_argument("--learning-rate", type=float, default=1e-4)
    ap.add_argument("--suffix", default="contextguard-v3")  # baked into the checkpoint ids; not renamed
    ap.add_argument("--poll", type=int, default=60, help="seconds between status checks")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", metavar="JOB_ID", help="only poll an existing job")
    args = ap.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    if not settings.nebius_configured:
        print("NEBIUS_API_KEY is not set")
        return 1
    client = AsyncOpenAI(base_url=settings.nebius_base_url, api_key=settings.nebius_api_key, max_retries=2, timeout=120)

    if args.status:
        state = load()
        state["job_id"] = args.status
        state = await poll(client, args.status, state, args.poll)
        status = state["job"]["status"]
        if status == "succeeded":
            await save_checkpoints(client, args.status, state)
        print(f"\nfinal status: {status}")
        return 0 if status == "succeeded" else 1

    train_p, valid_p = ROOT / args.train, ROOT / args.valid
    n_train, tok_train = validate_jsonl(train_p)
    n_valid, tok_valid = validate_jsonl(valid_p)
    print(f"train {n_train} examples (~{tok_train:,} tokens)   valid {n_valid} examples (~{tok_valid:,} tokens)")
    print(f"model {args.model}   lora r={args.lora_r}   epochs={args.epochs}   batch={args.batch_size}   lr={args.learning_rate}")
    hyper = {"lora": True, "lora_r": args.lora_r, "n_epochs": args.epochs, "batch_size": args.batch_size, "learning_rate": args.learning_rate}
    if args.dry_run:
        print("dry run: nothing uploaded, nothing created")
        print(json.dumps({"model": args.model, "hyperparameters": hyper, "suffix": args.suffix}, indent=2))
        return 0

    state = {"model": args.model, "hyperparameters": hyper, "train_examples": n_train, "valid_examples": n_valid, "started": time.time()}
    with train_p.open("rb") as fh:
        tf = await client.files.create(file=fh, purpose="fine-tune")
    state["training_file"] = tf.id
    print(f"uploaded training file {tf.id}")
    with valid_p.open("rb") as fh:
        vf = await client.files.create(file=fh, purpose="fine-tune")
    state["validation_file"] = vf.id
    print(f"uploaded validation file {vf.id}")
    save(state)

    job = await client.fine_tuning.jobs.create(
        model=args.model,
        training_file=tf.id,
        validation_file=vf.id,
        hyperparameters=hyper,
        suffix=args.suffix,
    )
    state["job_id"] = job.id
    state["job"] = job.model_dump()
    save(state)
    print(f"created job {job.id}  status={job.status}")
    print(f"state in {STATE.relative_to(ROOT)}")

    if args.no_wait:
        print(f"resume with: .venv/bin/python -m backend.eval.finetune --status {job.id}")
        return 0
    state = await poll(client, job.id, state, args.poll)
    status = state["job"]["status"]
    print(f"\nfinal status: {status}")
    if status == "succeeded":
        await save_checkpoints(client, job.id, state)
    return 0 if status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
