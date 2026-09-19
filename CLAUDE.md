# ContextGuard Social — working agreement

Chrome extension + FastAPI backend that analyses a post on X claim-first: extract the one main factual claim, check it against web evidence, say what context is missing, name the rhetorical signals with the words that triggered them, and give neutral speaker context. The verdict is about the claim, never about the post.

Built at HackBarna AI Summit 26 (19–20 Sept 2026). Code deadline Sunday 11:00.

## Who owns what

| Area | Owner | Path |
| --- | --- | --- |
| Backend, prompts, eval, fine-tune, SLNG media, docs | Ettore | `backend/`, `tests/`, `docs/` |
| Chrome extension (drawer, video button, demo) | Diana | `extension/` |

Do not edit the other owner's tree without a heads-up in the team chat. The contract between the two is `docs/API.md`.

## Contract rules

1. `backend/schemas/analysis_schema.py` is the source of truth. Any change to `AnalyzeResponse` or `PostAnalysis` bumps `SCHEMA_VERSION`, updates `docs/API.md`, and regenerates `tests/fixtures/responses_v3/`.
2. **Schema v3 is frozen.** v2 is withdrawn. After this, additive changes only (new optional fields), never renames or removals.
3. Canonical signal names live in `backend/prompts/taxonomy.py`. The extension may hard-code that list for badges; if it changes, both sides update.
4. **Field semantics go in the prompt text, not only in the schema.** Strict grammar mode does not show the model the schema descriptions: three models returned `manipulation_score: 0` for exactly this reason. If a field or an enum value has a meaning, write it in `backend/prompts/`.
4. Every endpoint is documented in the live OpenAPI at `http://127.0.0.1:8000/docs`.

## Run

```bash
uv venv .venv --python 3.11 && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env                      # add keys, or leave empty and use fake mode
ANALYZER_PROVIDER=fake .venv/bin/uvicorn backend.main:app --reload    # no keys needed
.venv/bin/pytest -q                       # offline, ~0.3 s
```

`make` lists every target; `make setup` does the three lines above, `make smoke` runs the tests
then boots the server and analyses a fixture post offline, `make docker-up` does the same in a
container. The Makefile is the single place run commands live — add new ones there, not to docs.

Extension: `make extension` (checks the contract, copies the path, opens the page), or by hand
`chrome://extensions` → Developer mode → Load unpacked → `extension/`. `make extension-check`
compares the backend taxonomy and verdicts against `extension/content/taxonomy.js` — run it after
any change to either side (rule 3 above).

## Providers

`ANALYZER_PROVIDER` = `nebius` (default, Token Factory, `openai/gpt-oss-120b`) | `gemini` (baseline, **no key set — every gemini arm fails**) | `fake` (deterministic, offline). Per-request override: `?provider=`. Prompt versions: `?prompt_version=v0` (spec prompt, the "before") or `v1` (guarded, default).

Validate the key and the whole pipeline in one command. Run it after any prompt change:

```bash
.venv/bin/python scripts/check_nebius.py --post spec_example
.venv/bin/python scripts/check_nebius.py --post weidel_immigration --model openai/gpt-oss-120b
.venv/bin/python scripts/check_nebius.py --list-models
```

It prints the five blocks the client renders, per-step latency and cost, and warns when a quote is not verbatim, a label is outside the taxonomy, or a cited URL was not in the evidence.

To compare two arms on one post. An arm is `provider[/model][:prompt_version]`:

```bash
make compare-models                  # two Nebius models, prompt v1 — the working comparison
make compare                         # prompt v1 vs v0, one model
.venv/bin/python scripts/compare.py --post spec_example \
  --variants nebius/openai/gpt-oss-120b:v1,nebius/Qwen/Qwen3-235B-A22B-Instruct-2507:v1
ANALYZER_PROVIDER=fake .venv/bin/python scripts/compare.py --post spec_example --variants fake:v0,fake:v1
```

**Compare models, not providers.** `GEMINI_API_KEY` is empty, so provider-against-provider
cannot run. One Nebius key reaches the whole catalogue (`make models`), and holding the
provider fixed is the fairer test anyway: same endpoint, same auth, same strict-JSON handling,
only the weights change. `model` exists only on `Variant` — the model is internal
configuration, so `/analyze`, `/claims` and `/analyze-claim` take no model parameter and the
extension never sends one.

Arms run **sequentially on purpose**: the Brave cache is keyed on the claim text, so parallel
arms would both miss it and spend two live searches. In order, arm 2 onward reuses arm 1's
evidence, which is also what makes the comparison fair. `POST /api/v1/compare` is the same
thing over HTTP. The three warnings live in `backend/eval/checks.py` and are shared with
`check_nebius.py`.

Measured on the benchmark posts: `openai/gpt-oss-120b` at `reasoning_effort=low` runs the two steps in 1.4 to 2.7 s; `Qwen/Qwen3-235B-A22B-Instruct-2507` takes 2.5 to 4 s; `Qwen/Qwen3-30B-A3B-Instruct-2507` took 27 s and is not usable. Reasoning models (GLM-Flash, DeepSeek-Flash, Nemotron-Lightning) spend the whole token budget thinking and fail.

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
