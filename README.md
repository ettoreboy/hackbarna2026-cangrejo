# ContextGuard Social

Chrome extension plus FastAPI backend that unpacks *why* a post on X is built the way it is: a neutral summary, who the author is, which communication signals and logical fallacies the text uses with the words that carry them, the strategic motive, a manipulation band, and one paragraph teaching the pattern.

It is **not a fact-checker** and never returns a true/false verdict.

Built at HackBarna AI Summit 26, Norrsken House Barcelona, 19–20 September 2026.

```
Chrome extension ── text ──▶ POST /api/v1/analyze ──────────────┐
                 ── video ─▶ POST /api/v1/analyze-media          │
                              yt-dlp → audio → SLNG STT (EU)     │
                              transcript ────────────────────────┤
                                                                 ▼
                            Wikipedia → Brave (author background)
                                                                 ▼
                            Nebius Token Factory (Qwen3-235B, strict JSON)
                            or Gemini 2.5 Flash (baseline) or fake (offline)
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

Analyse the benchmark post:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/analyze \
  -H 'content-type: application/json' \
  -d "$(python3 -c 'import json;print(json.dumps(json.load(open("tests/fixtures/posts.json"))["weidel_immigration"]["request"]))')" \
  | python3 -m json.tool
```

Extension: `chrome://extensions` → Developer mode → Load unpacked → `extension/`. Open x.com, click 🛡️ Context on any tweet.

Tests: `.venv/bin/pytest -q` (offline). Live check: `.venv/bin/pytest -q -m live -s`.

## Where each sponsor sits in the stack

| Sponsor | Role in the project |
| --- | --- |
| **Nebius Token Factory** | Primary analyzer. Qwen3-235B-A22B with strict `json_schema` output. Also hosts the LoRA fine-tune that adapts a 30B model to this schema and taxonomy. |
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
  services/analyzer_base.py      Analyzer protocol, AnalysisOutcome, AnalysisError
  services/nebius_service.py     Token Factory, strict json_schema        (WP1)
  services/gemini_service.py     Gemini 2.5 Flash baseline
  services/fake_service.py       deterministic offline provider
  services/background_service.py Wikipedia → Brave, never raises
  services/stt_service.py        SLNG speech-to-text                      (WP3)
  services/media_service.py      yt-dlp audio extraction                  (WP3)
  services/cache.py              TTL cache keyed by provider+model+prompt+post
  schemas/analysis_schema.py     schema v2, source of truth
  prompts/taxonomy.py            canonical signal and fallacy names
  prompts/context_prompt.py      system prompts v0 and v1, user prompt builder
  eval/                          balanced eval runner, metrics, fine-tune  (WP2, WP5)
extension/                       Chrome MV3 client (Diana)
tests/
  fixtures/posts.json            benchmark and control posts
  fixtures/responses_v2/         example API responses for the client
  test_analyzer.py               28 offline tests + 1 opt-in live test
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
- **Latency 2.5–4 s** on a cold text post, 8–15 s for video, near-instant when cached. The 1.5 s target in the original spec is discussed in `docs/ANALYSIS.md`.
- **Single-process cache.** Swap for Redis before running multiple workers.
- **No auth.** Localhost only. Add an API key header and rate limiting before hosting.
- **Not a fact-check.** Every response carries a disclaimer and its sources.

## Privacy

Post text, author name and handle go to your backend, then to the model provider, and for unknown authors to Brave. Video audio goes to SLNG pinned to an EU region. Nothing identifies the extension user.
