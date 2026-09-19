# Client handoff — Chrome extension

Written for: Diana, owning `extension/` from Saturday 19 Sept.

## What already works

Load `extension/` unpacked in Chrome and open x.com. You get:

- **Button injection**: `content/content.js` watches the timeline with a MutationObserver and adds a "🛡️ Context" button to every tweet's action bar. Every X selector is in the `SELECTORS` map at the top of the file. If X renames a `data-testid`, that map is the only place to fix.
- **Scraping**: on click it reads the tweet text, display name, `@handle`, canonical status URL, and sends `{type: "ANALYZE", payload}` to the service worker.
- **Service worker**: `background/background.js` POSTs to `/api/v1/analyze` on the backend URL from `chrome.storage.sync.backendUrl` (default `http://127.0.0.1:8000`) and returns `{ok, data}` or `{ok:false, error}`.
- **Drawer**: `content/overlay.js` renders a left-side drawer inside a Shadow DOM (X's CSS cannot leak in). Loading, error, and result states exist. Esc and ✕ close it.
- **Styles**: only the button lives in `styles/overlay.css`. Drawer CSS is a string inside `overlay.js`.

The drawer currently renders **schema v1**. The backend now returns **schema v2**. That mismatch is task 1.

## Run the backend with no keys

```bash
cd <repo>
uv venv .venv --python 3.11 && uv pip install --python .venv/bin/python -r requirements.txt
ANALYZER_PROVIDER=fake .venv/bin/uvicorn backend.main:app --reload
curl -s http://127.0.0.1:8000/api/v1/health
```

Fake mode returns deterministic responses. Tweets by `@Alice_Weidel` come back high, `@example_centrist` medium, `@destatis` low, `@troll_account` "Unknown author", anything else high. The same JSON files are in `tests/fixtures/responses_v2/` so you can also develop the drawer against static data.

To point the extension at a teammate's backend, in the service-worker console:

```js
chrome.storage.sync.set({ backendUrl: "http://192.168.x.y:8000" })
```

## Your tasks, in priority order

### 1. Render schema v2 in the drawer (Saturday afternoon)

Contract: `docs/API.md`, section "Field guide for rendering". Concretely in `overlay.js` `showResult`:

- `post_summary` first, as plain text under the post block.
- `score_band` is the hero element, colour-banded. Number small beside it.
- `communication_signals[]` badges: `name` as label, `evidence` as a quote under the badge or in the hover tip together with `description`. Hide Dog Whistle / Scapegoating / Dehumanization badges with `confidence < 0.6`. Names starting `Other: ` render muted.
- `logical_fallacies[]` chips with `evidence` on hover.
- `indicators.strategic_intent`, then `timing_note` small (skip when "No timing signal identified"), then `factual_context`.
- `indicators.is_division_tactic` → pill.
- `cognitive_summary` as the closing "Pattern to remember" section.
- Footer: provider, model, latency or "cached", disclaimer.
- Remove all references to `tactics_detected`, `strategic_intent`, `factual_context`, `is_division_tactic` at the top level; they moved.

Verify with all five fixture files. `text_unknown_author.json` must hide sources and show "Unknown author".

### 2. Video posts (Saturday evening; backend endpoint lands Saturday night, fake mode serves it earlier)

- In `content.js`, detect `article.querySelector("video")`. If present, the button reads "🛡️ Transcribe & Context" and sends `{type: "ANALYZE_MEDIA", payload: {post_url, author_handle, author_name, platform: "x"}}`.
- In `background.js`, route `ANALYZE_MEDIA` to `POST /api/v1/analyze-media`. Raise the fetch timeout to 45 s for this call.
- In `overlay.js`, staged loading on a timer: "Downloading audio" → "Transcribing (SLNG, EU region)" → "Analysing" at roughly 0 s / 4 s / 8 s. On result, show the `transcript.text` in the post block (label "Transcript · 23 s · en") above the analysis.
- Fixture: `tests/fixtures/responses_v2/media_example.json`.

### 3. Polish (Sunday morning)

- Error states: backend unreachable, 502 with detail, 413 video too long ("Videos over 60 s are not supported yet").
- Button state reset after close; re-click re-opens without refetch (backend caches anyway).
- Keyboard: Esc closes, focus returns to the button.
- Check at 1280 px and 1920 px widths; drawer must not cover the tweet being read on wide screens (consider docking right if the tweet is left of centre).

### 4. Demo recording (Sunday 09:30)

60–90 s screen recording: scroll timeline → click on a text post → drawer → click on a video post → transcript → drawer. Save as `docs/demo.mp4` or a public link in README.

## Things to know

- No X API is used and none should be. Everything comes from the DOM of the tweet on screen.
- Instagram is out of scope for this hackathon.
- Do not put any API key in the extension. The backend holds all keys.
- The canonical label list for badges is in `backend/prompts/taxonomy.py`. Copying it into a JS constant is fine.
- Backend owner: Ettore. Anything unclear in the contract, ask before guessing; changing `docs/API.md` is a two-person decision.

## Definition of done

- Drawer renders every field in `docs/API.md` for all fixture files.
- Text and video paths work end to end against a teammate's backend with real keys.
- Demo recording exists.
- `extension/` has no console errors on x.com.
