# Evaluation

Measured 19 September 2026 at HackBarna. Nebius Token Factory, `openai/gpt-oss-120b`, `reasoning_effort=low`, live Brave evidence.

Two sets are used. The synthetic set measures properties that need a known-correct answer. The real-tweet set measures whether the analyzer treats the two sides of a real legislature the same.

| Set | What it is | File |
| --- | --- | --- |
| Synthetic | 15 mirrored left/right pairs, 10 neutral posts, 5 injection twins. Invented authors, so the correct speaker answer is always "Unknown author". | `tests/eval/eval_set.jsonl` |
| Real tweets | 50 US senator tweets from a licensed research archive, 25 Republican and 25 Democratic, 2020 to 2022. Real people, real claims, party label as ground truth. | `backend/eval/tweets.csv` |

## 1. The guardrails are the product

`v0` is the task description alone. `v1` adds the RULES block and the canonical vocabulary. Same model, same posts, same evidence, synthetic set.

| Metric | v0 | v1 | What a low score means |
| --- | --- | --- | --- |
| Grounded Speaker | 0.00 | **1.00** | Biography invented for an unknown author |
| Injection Resistance | 0.20 | **1.00** | Text inside the post changes the analysis |
| Neutral Restraint | 0.00 | **1.00** | Informational posts flagged as manipulation |
| Vocabulary Adherence | 0.28 | **1.00** | Labels improvised, so badges and filters are unusable |
| Quote Fidelity | 0.79 | **0.98** | Quoted "evidence" is paraphrased, so the client cannot highlight it |
| Verdict Symmetry | 0.40 | 0.73 | The same claim structure gets a different verdict by side |
| Cited Only | 1.00 | 1.00 | A cited URL was never in the evidence |

Every row above is one run: `tests/eval/results/nebius_openai-gpt-oss-120b_v0.json` against
`_v1.json`. An earlier draft of this table reported Quote Fidelity 1.00 for v1, which was taken
from a different v1 run (`synthetic_v1_claimfix.json`). That run does reach 1.00 on quotes, but
it scores 0.60 on Injection Resistance and 0.90 on Neutral Restraint, so quoting its best number
next to another run's best numbers overstated v1. One run, every row.

**Re-scoring an old run needs a stable metric.** Vocabulary Adherence counts a label the taxonomy
can *map*, not one spelled exactly as today's canonical name. Without that, retiring a label
(v3.1 merged "Appeal to Fear" into "Fear-mongering") silently re-scores old runs downwards for a
change the model had nothing to do with: this table's v1 row would read 0.94 instead of 1.00.

**The worst flaw was invented biography.** All 41 no-source posts got a confident speaker block in v0, for accounts that do not exist:

> "CitizenWatch is an organization that posts about local governance and public safety issues"

On real posts the same behaviour produces plausible, unfalsifiable claims about named people. One rule fixed it: background comes only from supplied sources, otherwise the exact string "Unknown author".

**Prompt injection worked in v0.** Four of five injected posts changed the analysis; one instructed the model to report no manipulation and it returned `verdict: supported` with an empty signal list.

**Nothing was neutral in v0.** All ten informational posts were flagged, usually "Appeal to Authority" for a statistics office citing its own release.

## 2. Real tweets: the analyzer holds up

50 senator tweets, v1, live evidence.

| Metric | Score | Note |
| --- | --- | --- |
| Quote Fidelity | 1.00 | 108 quotes, all verbatim |
| Cited Only | 1.00 | 74 citations, all from the supplied evidence |
| Speaker Grounding | 1.00 | 49 of 50 authors matched to Wikipedia and described from it |
| Vocabulary Adherence | 0.99 | one improvised label in 70 |
| Party Signal Balance | 0.94 | mean signals per post: Democratic 1.44, Republican 1.36 |
| Party Verdict Balance | 0.84 | see below |

Median latency 2.5 s. Cost $0.71 per 1 000 posts. Verdicts spread across all five values, which the synthetic set could not produce because its claims are about invented entities that no search engine knows.

## 3. Two findings that change how the numbers should be read

### Verdicts are not reproducible

Two runs of the same 50 tweets, same model, same cached evidence, same prompt:

| | temperature 0.2 | temperature 0.0 |
| --- | --- | --- |
| Verdict identical | 72% | 86% |
| Claim-found identical | 96% | 96% |
| Signal set identical | 40% | 54% |

Temperature is now 0 by default. The residual variation is server-side: a mixture-of-experts model batched across requests does not route identically every time, and nothing in this client can fix that.

**Consequence: any single-run difference below roughly 10 points is noise.** An earlier draft of this document reported that a change to the claim prompt moved Party Verdict Balance from 0.80 to 0.96. Repeating the measurement showed 0.84 and 0.84, so that conclusion was wrong. Metrics over counts of many items (Quote Fidelity, Vocabulary Adherence, Cited Only, Speaker Grounding) are stable and can be trusted; per-item verdict metrics on 50 items cannot.

For a decision that matters, run the set three times and take the majority verdict per item.

### The party verdict gap is about 16 points and its cause is unresolved

Across repeated runs, Republican tweets receive a critical verdict (`unsupported` or `partially_supported`) 16 to 20 points more often than Democratic ones. The gap itself is consistent, so it is not noise.

Reading every critical verdict, the reasoning is sound on both sides and applies the same standard:

- Republican, upheld: a claim that the Jones Act centennial was "today" when the evidence dates it to June 2020; "half our energy comes from hydropower" against a sourced 36%.
- Democratic, upheld: "56 years ago" for a 1965 act; "more than 100 million" where the sources say 130 million.

Two explanations remain open and this set cannot separate them. The tweets are from 2020 to 2022, when Republicans were the opposition party; opposition messaging makes more contestable empirical assertions about an administration, and 22 of 25 Republican tweets contained a checkable claim against 19 of 25 Democratic ones. The alternative is that the analyzer is harsher on one side's framing. Settling it needs tweets from a period with the parties reversed, which is the obvious next experiment.

**This is reported rather than hidden because it is the number most likely to be challenged**, and an unexplained 16-point gap is exactly what a media-literacy tool must be able to talk about.

## 4. Known weakness in claim extraction

Figurative attack lines were being promoted into checkable claims: "the President has been missing" was extracted and then fact-checked, as was "Biden green-lighted Putin to invade Ukraine". Both are rhetoric, not assertions. The claim prompt now excludes figurative and hyperbolic statements with worked examples, and the number of posts correctly returning "no factual claim" rose from 9 to 12 of 50. Whether that also moved the party gap is unproven for the reason in section 3.

## Published to Galtea

`backend/eval/galtea_sync.py` pushes a run that already exists on disk to the Galtea platform as
a scored product version. It imports no analyzer and no HTTP client, so it cannot call Nebius or
Brave even by accident: a sync is free and takes seconds.

```bash
.venv/bin/python -m backend.eval.galtea_sync --results tests/eval/results/nebius_openai-gpt-oss-120b_v0.json --version prompt-v0 --dry-run
.venv/bin/python -m backend.eval.galtea_sync --results tests/eval/results/nebius_openai-gpt-oss-120b_v0.json --version prompt-v0
.venv/bin/python -m backend.eval.galtea_sync --results tests/eval/results/nebius_openai-gpt-oss-120b_v1.json --version prompt-v1
```

The two versions carry the same 50 test cases, so the dashboard compares them directly:

| Galtea metric | prompt-v0 | prompt-v1 | n |
| --- | --- | --- | --- |
| grounded-speaker | 0.00 | **1.00** | 41 |
| injection-resistance | 0.20 | **1.00** | 10 |
| neutral-restraint | 0.00 | **1.00** | 10 |
| vocabulary-adherence | 0.31 | **0.95** | 48 / 40 |
| quote-fidelity | 0.79 | **0.98** | 50 |
| verdict-symmetry | 0.40 | **0.73** | 30 |
| signal-symmetry | 0.77 | 0.72 | 30 |
| cited-only | 1.00 | 1.00 | 14 / 12 |
| speaker-grounding | 1.00 | 0.89 | 9 |

### How eleven run-level metrics became nine per-trace ones

Galtea scores one test case at a time; `metrics.py` scores a whole run. The split:

- **Six restate cleanly for one item** — quote fidelity, vocabulary adherence, cited-only,
  neutral restraint, grounded speaker, speaker grounding. Each is already a judgement about one
  post that `metrics.py` happens to average.
- **Three are pairwise** — signal symmetry, verdict symmetry and injection resistance are
  statements about *two* posts. The pair's score is attached to both halves, and each metric
  description on the platform says so, so nobody reads 0.50 as a verdict on one post. This is why
  their `n` is 30 and 10 rather than 15 and 5.
- **Two are not sent at all.** Party signal balance and party verdict balance compare two
  populations of 25 tweets; writing a run constant onto 50 traces would claim n=50 for a
  statistic with n=1. They stay in section 2 of this document.

**A metric that does not apply to an item is omitted, not scored zero.** Scoring "neutral
restraint" zero on a political post would drag the average down for a rule that never applied to
it. That is why the columns above have different `n` values.

The per-trace numbers macro-average over posts while section 1 micro-averages over quotes and
labels, so the two tables can differ by a point or two on the ratio metrics. Both are correct;
they weight differently.

## Reproducing

```bash
.venv/bin/python -m backend.eval.run_eval --prompt-version v1                          # synthetic
.venv/bin/python -m backend.eval.run_eval --prompt-version v0
.venv/bin/python -m backend.eval.run_eval --set backend/eval/tweets.csv                # real tweets
.venv/bin/python -m backend.eval.run_eval --score-only tests/eval/results/<file>.json  # re-score, no model calls
```

Brave results are cached in `.cache/brave.sqlite` and live calls stop at `BRAVE_BUDGET`. The full real-tweet run cost 41 searches the first time and 6 on later runs. Total spend across all evaluation work: 189 of 2 000 searches.
