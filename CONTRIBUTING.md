# Contributing to Unfold

Thanks for looking. This is a hackathon project that outgrew the weekend, so the rules are short.

## Get it running in three commands

```bash
make setup                          # venv, deps, .env from .env.example
make run-fake                       # API on :8000, offline, no API keys needed
make test                           # 125 offline tests, about 5 seconds
```

`make` on its own lists every target. The Makefile is the single place run commands live — if you
add a new way to run something, add it there, not to a document.

You do not need an API key to contribute. `ANALYZER_PROVIDER=fake` gives a deterministic analyser
that returns fixture responses, and the whole test suite runs against it offline.

## Who owns what

| Area | Owner | Path |
| --- | --- | --- |
| Backend, prompts, eval, fine-tune, docs | Ettore | `backend/`, `tests/`, `docs/`, `scripts/` |
| Chrome extension | Diana | `extension/` |

The contract between the two trees is [`docs/API.md`](docs/API.md). A change that crosses the line
needs a heads-up to the other owner on the pull request.

## The four rules that will fail your PR

**1. The schema is frozen.** `backend/schemas/analysis_schema.py` is the source of truth, and
schema v3 is frozen. Additive changes only — a new optional field is fine, a rename or a removal is
not. Any change to `AnalyzeResponse` or `PostAnalysis` bumps `SCHEMA_VERSION`, updates
`docs/API.md`, and regenerates `tests/fixtures/responses_v3/`.

**2. The taxonomy lives in two places and both must move together.** Canonical signal names are in
`backend/prompts/taxonomy.py`; the extension hard-codes the same list in
`extension/content/taxonomy.js` for its badges. After touching either, run:

```bash
make extension-check
```

CI runs this too, so a mismatch fails the build rather than reaching a demo.

**3. Field meaning goes in the prompt, not only in the schema.** Strict grammar mode does not show
the model the schema descriptions. Three models returned `manipulation_score: 0` for exactly that
reason. If a field or an enum value has a meaning, write it in `backend/prompts/`.

**4. `standard` rigor must stay byte-identical to what `docs/EVAL.md` measured.**
`tests/test_pipeline.py` asserts it. Otherwise the published v0-versus-v1 ablation silently stops
describing the prompt that actually ships. Put new scrutiny in `backend/prompts/rigor.py` under
`strict`.

## Changing a prompt

A prompt change is a behaviour change, so it needs evidence, not just a green test run:

```bash
make check-fake                                   # pipeline offline, no key, no Brave spend
.venv/bin/python scripts/check_nebius.py --post spec_example      # needs NEBIUS_API_KEY
make compare POST=merz_tenpoint                   # v1 against v0, one model
```

`check_nebius.py` prints the five blocks the client renders, per-step latency and cost, and warns
when a quote is not verbatim, a label falls outside the taxonomy, or a cited URL was not in the
evidence. Paste the relevant part into the pull request.

Compare models, not providers. `GEMINI_API_KEY` is empty in this project, so a provider-against-
provider run cannot happen; one Nebius key reaches the whole catalogue and holding the provider
fixed is the fairer test anyway.

## Style

- **Python**: type hints, `from __future__ import annotations`. No new dependency without a line in
  `requirements.txt` and a sentence in the PR saying why.
- **JavaScript**: vanilla, no build step. Anything injected into X goes in a Shadow DOM.
- **Commits**: small, early, imperative mood — "Add the strict rigor block", not "Added" or
  "Adding". Never commit `.env`.
- **Tests stay green before every push.** `make smoke` runs the suite, the extension contract and
  an offline end-to-end pass in one go.

## Opening a pull request

1. Branch off `main`.
2. Make the change, keep it one topic.
3. Run `make smoke`.
4. Open the PR and fill in the template — what changed, how you checked it, what it touches.

`main` is protected: force-pushes and deletion are blocked, and CI has to pass before merge.

## Testing the extension by hand

```bash
make extension          # checks the contract, copies the path, opens chrome://extensions
```

Then Developer mode → Load unpacked → `extension/`. After an edit, `make extension-reload` tells
you what to press; the backend does not need restarting.

## Reporting something

- A bug or an idea → [open an issue](https://github.com/ettoreboy/unfold/issues/new/choose).
- A security problem → do not open an issue, read [SECURITY.md](SECURITY.md).
- Anything about conduct → [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
