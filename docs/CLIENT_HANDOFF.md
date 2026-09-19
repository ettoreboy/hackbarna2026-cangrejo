# Client handoff — Chrome extension

Written for: Diana, owning `extension/`.

## Read this first

The response shape changed. **Schema v3 replaces v2.** If you already started on the v2 drawer, stop and re-read `docs/API.md`: there is no manipulation score, no post summary, no intent field. The product is now claim-first.

One post produces five blocks, in this reading order:

```
MAIN CLAIM          the single verifiable factual claim, or "none found"
CLAIM CHECK         supported / partially supported / unsupported / unverifiable / no factual claim
                    + one-sentence explanation + source links
MISSING CONTEXT     one or two sentences, or absent
RHETORICAL SIGNALS  badges, each with the exact words from the post that triggered it
SPEAKER CONTEXT     name · role, one or two neutral sentences
```

The verdict is about the claim, never about the post. The UI must not say the post is true or false.

## What already works in `extension/`

- **Button injection**: `content/content.js` watches the timeline with a MutationObserver and adds a "🛡️ Context" button to every tweet's action bar. Every X selector is in the `SELECTORS` map at the top of the file; a DOM change is a one-place fix.
- **Scraping**: on click it reads the tweet text, display name, `@handle` and canonical status URL, and sends `{type: "CLAIMS", payload}` to the service worker.
- **Service worker**: `background/background.js` is the only part that touches the network — a fetch from a content script runs with x.com's origin and X's CSP blocks localhost. It POSTs to the backend URL from `chrome.storage.sync.backendUrl` (default `http://127.0.0.1:8000`) and returns `{ok, data}` or `{ok:false, error}`.
- **Card**: `content/card.js` renders the analysis inline under the tweet inside a Shadow DOM, so X's CSS cannot leak in. Loading, error and result states exist.

The live path is two-stage: `CLAIMS` → `POST /api/v1/claims` lists what is checkable, the reader
picks one, `ANALYZE_CLAIM` → `POST /api/v1/analyze-claim` checks that one. `{type: "ANALYZE"}`
and `/api/v1/analyze` are a one-shot fallback the card no longer uses.

## Run the backend with no keys

```bash
uv venv .venv --python 3.11 && uv pip install --python .venv/bin/python -r requirements.txt
ANALYZER_PROVIDER=fake .venv/bin/uvicorn backend.main:app --reload
curl -s http://127.0.0.1:8000/api/v1/health
```

Fake mode is deterministic and covers every branch you need to render:

| Handle to post as | You get |
| --- | --- |
| `example_migrants` | claim found, `partially_supported`, two sources, one signal |
| `destatis` | claim found, `supported`, one source, no signals |
| `Alice_Weidel` | claim found, `unverifiable` (no evidence), four signals, Wikipedia speaker |
| `example_left_mp` | no claim, `no_factual_claim`, three signals |
| `troll_account` | no claim, `Unknown author` speaker |

The same payloads are static files in `tests/fixtures/responses_v3/` if you prefer to build against JSON without running anything.

To point the extension at a teammate's backend, in the service-worker console:

```js
chrome.storage.sync.set({ backendUrl: "http://192.168.x.y:8000" })
```

## Your tasks, in priority order

### 1. Render schema v3 (the whole job) — DONE

Diana shipped this, then went further: the drawer was rebuilt around a two-stage claim picker
(`POST /api/v1/claims` then `POST /api/v1/analyze-claim`) and the analysis now renders inline in
the tweet as an Unfold card. `content/overlay.js` is gone; `content/card.js` replaced it.

The field requirements below still hold, so keep them in mind when changing the card. Each case
must look right:

- **No claim.** `main_claim.found === false`: say "No checkable factual claim in this post" and render the verdict pill as neutral grey, not as a failure.
- **Unverifiable.** Common and not an error. Grey pill, empty source list, explanation still shown.
- **Empty `missing_context`** and **empty `rhetorical_signals`**: hide those blocks entirely rather than showing an empty heading.
- **`Unknown author`**: show it plainly and hide the background sources list.
- **`Other: ` prefixed signal names**: render muted, they are outside the known vocabulary.
- Every signal badge must show its `evidence` quote, under the badge or on hover. That quote is the product's whole credibility; do not drop it.

Canonical signal names are in `backend/prompts/taxonomy.py` if you want fixed colours or icons per name.

### 2. Video posts — CANCELLED

> The SLNG track was dropped to finish the text path. `POST /api/v1/analyze-media` does not
> exist and will not before the deadline. Do not build against it. Keep the video detection
> in `content.js` only to tell the reader there is nothing to analyse yet.


- In `content.js`, detect `article.querySelector("video")`. If present the button reads "🛡️ Transcribe & Context" and sends `{type: "ANALYZE_MEDIA", payload: {post_url, author_handle, author_name, platform: "x"}}`.
- In `background.js`, route that to `POST /api/v1/analyze-media` with a 45 s timeout.
- In `overlay.js`, staged loading on a timer: "Downloading audio" → "Transcribing (SLNG, EU region)" → "Analysing", roughly 0 s / 4 s / 8 s. On result show `transcript.text` above the analysis, labelled "Transcript · 23 s · en".
- Fixture: `tests/fixtures/responses_v3/media_example.json`.

### 3. Polish

Error states (backend unreachable, 502 with detail, 413 "Videos over 60 s are not supported yet"), button state reset after close, Esc returns focus to the button, check 1280 px and 1920 px. On wide screens consider docking right when the tweet sits left of centre.

### 4. Demo recording, Sunday 09:30 (text path only)

60 to 90 seconds, text path only: scroll the timeline, click Unfold on a post, show the claim list, pick a claim, show the verdict with its citations. Save as `docs/demo.mp4` or a public link in the README.

## Things to know

- No X API is used and none should be. Everything comes from the DOM of the tweet on screen.
- Instagram is out of scope.
- No API key goes in the extension. The backend holds all keys.
- Backend owner: Ettore. `docs/API.md` is the contract; changing it is a two-person decision.

## Definition of done

- Every field in `docs/API.md` renders, and all six fake-mode handles look right.
- The text path works against a backend with real keys. There is no video path.
- Demo recording exists.
- No console errors on x.com.
