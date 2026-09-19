# Unfold

Chrome extension plus FastAPI backend that analyses a post on X claim-first:

1. **Main claim** — the one independently verifiable factual claim in the post, separated from opinion and rhetoric.
2. **Claim check** — that claim against web evidence: supported, partially supported, unsupported, or unverifiable, with sources.
3. **Missing context** — what a reader needs to know that the post leaves out.
4. **Rhetorical signals** — how the post is written, each with the exact words that triggered it.
5. **Speaker context** — who the author is, neutrally.

The verdict is about the claim, never about the post. The tool does not label posts true or false and does not guess at the author's intentions.

Built at HackBarna AI Summit 26, Norrsken House Barcelona, 19–20 September 2026.

```
Chrome extension ── text ──▶ POST /api/v1/analyze
                 ── video ─▶ POST /api/v1/analyze-media → yt-dlp → SLNG STT (EU)
                                        │
                     step 1 ────────────┴──▶ extract main claim        (model)
                     step 2  Brave search on the claim  +  Wikipedia→Brave on the author
                     step 3  claim check · missing context · signals · speaker  (model, strict JSON)

Models: Nebius Token Factory (gpt-oss-120b default) · Gemini 2.5 Flash (baseline) · fake (offline)
Measured end to end: 1.4–2.7 s
```

## Quick start

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env                  # add NEBIUS_API_KEY, or skip and use fake mode
.venv/bin/uvicorn backend.main:app --reload
```

No keys? `ANALYZER_PROVIDER=fake .venv/bin/uvicorn backend.main:app --reload` serves deterministic responses.

Check: `curl http://127.0.0.1:8000/api/v1/health`

Or use the task runner — `make` lists every target:

```bash
make setup        # venv, deps, .env
make run-fake     # server, offline, no keys
make smoke        # tests, then a full offline request against a booted server
make extension    # load the Chrome extension (checks it agrees with the backend first)
make check POST=spec_example   # the real pipeline on one post, with latency and cost
```

Docker, if you would rather not touch Python:

```bash
make docker-up    # fake mode on :8000, no keys
make docker-up-live   # same image, keys from .env
make docker-down
```


Analyse the benchmark post:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H 'content-type: application/json' \
  -d "$(python3 -c 'import json;print(json.dumps(json.load(open("tests/fixtures/posts.json"))["weidel_immigration"]["request"]))')" \
  | python3 -m json.tool
```

Extension: `make extension` copies the path and opens the page, or by hand `chrome://extensions` → Developer mode → Load unpacked → `extension/`. Open x.com, click **Unfold** on any tweet.

`make extension-check` compares the two trees: the port the drawer calls, the verdict values and the high-risk signal names against `backend/prompts/taxonomy.py`. Chrome 137 and later ignore `--load-extension`, so the four clicks cannot be scripted.

Tests: `.venv/bin/pytest -q` (offline). Live check: `.venv/bin/pytest -q -m live -s`.

## Where each sponsor sits in the stack

| Sponsor | Role in the project |
| --- | --- |
| **Nebius Token Factory** | Both model calls. `gpt-oss-120b` with strict `json_schema` output at `reasoning_effort=low`. Also hosts the LoRA fine-tune that adapts a smaller model to this schema and taxonomy. |
| **Galtea** | Evaluation. Finds the worst flaw (partisan asymmetry, prompt injection) and proves the guarded prompt fixes it. Custom self-hosted metrics. |
| **SLNG** | Speech-to-text for video posts. Deepgram Nova 3 over the EU region so audio never leaves the EU. |

See `docs/EVAL.md` for the numbers.

## Owners

| Area | Owner |
| --- | --- |
| `backend/`, `tests/`, `docs/` | Ettore |
| `extension/` | Diana |

The contract between the two is `docs/API.md`. Working agreement: `CLAUDE.md`. Client brief: `docs/CLIENT_HANDOFF.md`.

## Layout

```
backend/
  main.py                        app factory, provider registry, CORS
  config.py                      settings; ANALYZER_PROVIDER picks the analyzer
  routers/analyze.py             /analyze, /health
  routers/compare.py             /compare: one post, several arms, side by side
  services/analyzer_base.py      Analyzer protocol, AnalysisOutcome, AnalysisError
  services/pipeline.py           the three steps, timed
  services/compare.py            sequential arms, shared evidence, agreement diff
  services/evidence_service.py   Brave search for the extracted claim
  services/nebius_service.py     Token Factory, strict json_schema, both steps
  services/schema_tools.py       Pydantic schema -> strict structured output
  services/pricing.py            token price table, NEBIUS_PRICES override
  services/gemini_service.py     Gemini 2.5 Flash baseline
  services/fake_service.py       deterministic offline provider
  services/background_service.py Wikipedia → Brave, never raises
  services/stt_service.py        SLNG speech-to-text                      (WP3)
  services/media_service.py      yt-dlp audio extraction                  (WP3)
  services/cache.py              TTL cache keyed by provider+model+prompt+post
  schemas/analysis_schema.py     schema v3, source of truth
  prompts/taxonomy.py            canonical rhetorical-signal names
  prompts/claim_prompt.py        step 1: main claim extraction
  prompts/context_prompt.py      step 3: prompts v0 and v1, user prompt builder
  eval/                          balanced eval runner, metrics, fine-tune  (WP2, WP5)
  eval/checks.py                 per-response quote, taxonomy and citation checks
scripts/check_nebius.py          one-command validation of a Nebius key
scripts/compare.py               side-by-side run of two to four arms on one post
scripts/_render.py               terminal rendering shared by both scripts
extension/                       Chrome MV3 client (Diana)
tests/
  fixtures/posts.json            benchmark and control posts
  fixtures/responses_v3/         example API responses for the client
  test_pipeline.py               pipeline behaviour on the fake provider
  test_nebius.py                 provider: strict schema, fallback, errors, cost
  test_gemini.py                 provider: determinism, salvage, failure modes, cost
  test_compare.py                /compare: arms, shared evidence, arm failure
docs/
  API.md                         the contract
  CLIENT_HANDOFF.md              brief for the extension developer
  TECHNIQUES.md                  every tactic, fallacy and mechanism with detection cues
  PROMPT_DESIGN.md               prompt rationale and guardrails
  ANALYSIS.md                    critical analysis of the original spec
  EVAL.md                        measured results                          (WP2, WP4)
```

## Known limits

- **X only.** Instagram selectors change too often.
- **Latency 1.4–2.7 s** on a cold text post (two model calls plus search), 8–15 s for video, near-instant when cached.
- **A claim check needs evidence.** Without `BRAVE_API_KEY` every verdict is `unverifiable`, which is honest but makes a poor demo.
- **Single-process cache.** Swap for Redis before running multiple workers.
- **No auth.** Localhost only. Add an API key header and rate limiting before hosting.
- **Not a fact-check.** The verdict covers one extracted claim against the sources listed, nothing more. Every response carries a disclaimer.

## Privacy

Post text, author name and handle go to your backend, then to the model provider, and for unknown authors to Brave. Video audio goes to SLNG pinned to an EU region. Nothing identifies the extension user.
