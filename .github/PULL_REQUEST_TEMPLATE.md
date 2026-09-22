## What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The problem, or the demo that needed it. Link an issue with "Closes #12" if there is one. -->

## How I checked it

<!-- Delete what does not apply. Paste output where it helps. -->

- [ ] `make test` — offline suite green
- [ ] `make extension-check` — backend and extension still agree
- [ ] `make smoke` — tests, contract, offline end-to-end
- [ ] Prompt change: `scripts/check_nebius.py` output pasted below
- [ ] Extension change: loaded unpacked and clicked through a real post on X

## Contract

<!-- Tick anything this touches. Each one has a rule in CONTRIBUTING.md. -->

- [ ] Touches `backend/schemas/analysis_schema.py` — `SCHEMA_VERSION` bumped, `docs/API.md`
      updated, `tests/fixtures/responses_v3/` regenerated
- [ ] Touches the signal taxonomy — both `backend/prompts/taxonomy.py` and
      `extension/content/taxonomy.js` updated
- [ ] Touches `standard` rigor prompts — I have read why they must stay byte-identical
- [ ] Adds a dependency — added to `requirements.txt`, reason given above
- [ ] Crosses the backend/extension line — the other owner has been told

## Anything a reviewer should look at first

<!-- A file, a trade-off you are unsure about, or "nothing, it is small". -->
