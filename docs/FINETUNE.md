# Fine-tuning: what was built, and why

The goal is a small model that reproduces the guarded step-3 behaviour of the big one. Not new
knowledge — the format, the vocabulary and the restraint rules. Facts stay in the evidence.

Teacher `openai/gpt-oss-120b`, student `Qwen/Qwen3-30B-A3B-Instruct-2507`, LoRA, on Nebius
Token Factory.

## What the student is trained on

**Step 3 only.** One training example is the whole step-3 exchange: the v1 system prompt, the
user prompt (post, extracted claim, evidence sources, author background) and the assistant's
JSON body. Step 1 (claim extraction) stays on the base model at inference, so the student never
has to learn two jobs.

## The four stages

```bash
.venv/bin/python -m backend.eval.make_ft_set --repeats 3
```

1. **Generate** — 298 synthetic posts on topics disjoint from the eval set: 100 mirrored
   left/right pairs, 60 neutral, 20 injection twins. Every person and organisation is invented,
   so nothing in this set can leak a real political judgment into the weights.
2. **Label** — each post through the real v1 pipeline with the teacher.
3. **Filter** — drop every example the teacher demonstrably got wrong.
4. **Write** — `tests/eval/ft_train.jsonl` (175) and `ft_valid.jsonl` (19), plus
   `ft_report.json` (why each example was dropped) and `ft_review.md` (12 random examples in
   readable form, for the human pass).

## Two decisions that shape the data

**Evidence is synthesised, not searched.** The posts are about invented entities, so a real web
search returns nothing relevant and the teacher correctly answers `unverifiable` every single
time. A dataset with one verdict teaches the student one word. Instead each post is assigned a
target verdict, sources are written so that target is the correct answer, and the example is
kept only if the teacher independently reaches it. Teacher and target agreed 85% of the time.
Side effect: **zero Brave spend** for the whole dataset.

**Every post is labelled three times and disagreements are thrown away.** Verdicts on this
model are not reproducible: two identical runs agree on 86% of them at temperature 0
(`docs/EVAL.md` section 3). Distilling a teacher that flips one answer in seven bakes that noise
into the weights. The claim and the evidence are pinned after run 1, so the repeats vary only
step 3 — the step being distilled. 272 of 298 posts survived; 13 had an unstable verdict and 10
an unstable signal count.

## What survived

194 of 298 kept. Balanced by side, spread across every verdict:

| By side | | By verdict | |
| --- | --- | --- | --- |
| right | 65 | supported | 76 |
| left | 64 | unverifiable | 49 |
| neutral | 45 | partially_supported | 28 |
| injection | 20 | unsupported | 26 |
| | | no_factual_claim | 15 |

Right and left are within one example of each other by construction: both halves of a mirrored
pair get the **same** target verdict, so the student cannot learn that one side gets a softer
answer.

Top reasons for dropping: teacher verdict disagreed with the target (34), quote not verbatim
(21), verdict or signal count unstable across runs (23), invented speaker background (10),
injection changed the verdict (7), label outside the taxonomy (5).

## The job

```bash
.venv/bin/python -m backend.eval.finetune --dry-run     # validate files, create nothing
.venv/bin/python -m backend.eval.finetune --no-wait
.venv/bin/python -m backend.eval.finetune --status ftjob-xxxx
```

`Qwen/Qwen3-30B-A3B-Instruct-2507`, LoRA r=16, 3 epochs, batch 16, lr 1e-4, suffix
`contextguard-v3`. Job id and the full event log land in `tests/eval/results/finetune.json`.

**Batch size must be at least 16.** Nebius rejects a job where `batch_size * 8192 < 131072`;
batch 8 returns a 422.

## Two open risks, stated plainly

1. **Serving the result is beta-on-request on Nebius.** A trained adapter that cannot be served
   cannot be benchmarked against the teacher. Ask the Nebius mentors to enable custom weights.
2. **The student may be too slow even if served.** `Qwen3-30B-A3B` measured 27 s on the
   benchmark post through this pipeline, against 1.4–2.7 s for the teacher. If that holds after
   fine-tuning, the fine-tune is a research result rather than the production path, and
   `openai/gpt-oss-120b` stays the served model.
