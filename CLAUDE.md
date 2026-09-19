# ContextGuard Social — working agreement

Chrome extension + FastAPI backend that unpacks *why* a post on X is built the way it is: post summary, author background, communication signals with quoted evidence, logical fallacies, strategic indicators, a manipulation band, and a one-paragraph lesson. Not a fact-checker.

Built at HackBarna AI Summit 26 (19–20 Sept 2026). Code deadline Sunday 11:00.

## Who owns what

| Area | Owner | Path |
| --- | --- | --- |
| Backend, prompts, eval, fine-tune, SLNG media, docs | Ettore | `backend/`, `tests/`, `docs/` |
| Chrome extension (drawer, video button, demo) | Diana | `extension/` |

Do not edit the other owner's tree without a heads-up in the team chat. The contract between the two is `docs/API.md`.

## Contract rules

1. `backend/schemas/analysis_schema.py` is the source of truth. Any change to `AnalyzeResponse` or `AnalysisResult` bumps `SCHEMA_VERSION`, updates `docs/API.md`, and regenerates `tests/fixtures/responses_v2/`.
2. Schema v2 is **frozen from Sat 19 Sept 16:00**. After that, additive changes only (new optional fields), never renames or removals.
3. Canonical labels live in `backend/prompts/taxonomy.py`. The extension may hard-code that list for badges; if it changes, both sides update.
4. Every endpoint is documented in the live OpenAPI at `http://127.0.0.1:8000/docs`.

## Run

```bash
uv venv .venv --python 3.11 && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env                      # add keys, or leave empty and use fake mode
ANALYZER_PROVIDER=fake .venv/bin/uvicorn backend.main:app --reload    # no keys needed
.venv/bin/pytest -q                       # offline, ~0.3 s
```

Extension: `chrome://extensions` → Developer mode → Load unpacked → `extension/`.

## Providers

`ANALYZER_PROVIDER` = `nebius` (default, Token Factory, Qwen3-235B) | `gemini` (baseline) | `fake` (deterministic, offline). Per-request override: `?provider=`. Prompt versions: `?prompt_version=v0` (spec prompt, the "before") or `v1` (guarded, default).

Validate a new Nebius key in one command:

```bash
.venv/bin/python scripts/check_nebius.py              # auth, model, strict JSON, one real analysis
.venv/bin/python scripts/check_nebius.py --list-models
```

Two things to know when working on `nebius_service.py`:

- **The openai SDK vendors its own HTTP stack (`httpx2`)**, so respx does not intercept it. Mock the model endpoint with `tests/nebius_mock.py`, not respx. Wikipedia and Brave use plain httpx and are still respx-mocked.
- **Strict `json_schema` is not universal.** Pydantic schemas are sanitised by `schema_tools.to_strict_schema` (adds `additionalProperties: false`, makes every property required, drops keywords outside the subset). If a model rejects strict mode the provider retries once with `json_object` and remembers the downgrade for the process.

Prices are not in the public docs. `backend/services/pricing.py` holds the table read from the console; override without code via `NEBIUS_PRICES='{"model/id": [in, out]}'` in USD per 1M tokens. An unpriced model reports `cost_usd: null` rather than a guess.

## Sponsor tracks in scope

Nebius (analyzer + fine-tune), Galtea (worst-flaw eval), SLNG (speech-to-text for video posts). Nothing else.

## Conventions

- Commit early, commit small, message in imperative mood. Never commit `.env`.
- Python: type hints, `from __future__ import annotations`, no new deps without adding to `requirements.txt`.
- JS: vanilla, no build step, Shadow DOM for anything injected into X.
- Tests must stay green before every push.
