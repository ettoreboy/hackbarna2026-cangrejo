# API contract (schema v3, claim-first)

**v3 replaces v2. v2 is withdrawn; do not render it.** The response no longer carries a manipulation score, a post summary or an intent field. It carries one extracted claim, a verdict on that claim, missing context, rhetorical signals, and speaker context.

Base URL in development: `http://127.0.0.1:8000`. Live OpenAPI: `/docs`.

CORS allows origins `chrome-extension://<32 lowercase letters>` and `http(s)://localhost` / `127.0.0.1` on any port. Only `content-type` may be sent as a custom header.

## What the backend does with one post

1. **Claim extraction.** A model reads the post and returns the single main factual claim, restated as a standalone sentence plus the verbatim words it came from. Opinions, predictions and rhetoric are not claims. A post can legitimately have none.
2. **Evidence.** The claim text is searched on the web. Skipped when there is no claim.
3. **Analysis.** A second model call checks the claim against that evidence only, names what context is missing, lists rhetorical signals with the words that triggered them, and summarises who the author is from Wikipedia.

Measured live on Nebius `openai/gpt-oss-120b`: 1.4 to 2.7 s end to end.

## Offline mode

```bash
ANALYZER_PROVIDER=fake uvicorn backend.main:app --reload
```

Deterministic v3 responses, no API keys. Handles `Alice_Weidel`, `example_migrants`, `example_left_mp`, `example_centrist`, `destatis` and `troll_account` hit specific fixtures. The same payloads are in `tests/fixtures/responses_v3/`.

## `GET /api/v1/health`

```json
{ "status": "ok", "schema_version": "3", "providers": ["fake"], "default_provider": "fake", "brave_configured": false, "slng_configured": false }
```

## `POST /api/v1/analyze`

Query params, all optional: `provider=nebius|gemini|fake`, `prompt_version=v0|v1`, `nocache=true`.

Request (unchanged from v2):

```json
{
  "author_handle": "example_migrants",
  "author_name": "Example Account",
  "post_text": "Germany accepted 1.2M migrants last year. This government clearly doesn't care about German citizens.",
  "platform": "x",
  "post_url": "https://x.com/example/status/1000000000000000001"
}
```

Response, abridged. Full example: `tests/fixtures/responses_v3/claim_partially_supported.json`.

```json
{
  "schema_version": "3",
  "analysis": {
    "main_claim": {
      "found": true,
      "text": "Germany accepted 1.2 million migrants last year.",
      "quote": "Germany accepted 1.2M migrants last year."
    },
    "claim_check": {
      "verdict": "partially_supported",
      "explanation": "The direction is reported by the sources but the scale and timeframe in the post are not.",
      "sources": [{ "title": "Migration report 2025", "url": "https://www.bamf.example/report-2025" }]
    },
    "missing_context": "The figure mixes asylum applications with all forms of immigration, and a large share were Ukrainian refugees under temporary protection.",
    "rhetorical_signals": [
      { "name": "Loaded Language", "evidence": "clearly doesn't care about German citizens" }
    ],
    "speaker_context": { "name": "Example Account", "role": "", "background": "Unknown author" }
  },
  "evidence": [ { "title": "...", "url": "...", "snippet": "...", "provider": "brave" } ],
  "sources":  [ { "title": "...", "url": "...", "snippet": "...", "provider": "wikipedia" } ],
  "transcript": null,
  "steps": { "extract_ms": 640, "evidence_ms": 520, "analyse_ms": 1220 },
  "cached": false,
  "latency_ms": 2380,
  "provider": "nebius",
  "model": "openai/gpt-oss-120b",
  "cost_usd": 0.00053,
  "disclaimer": "AI-generated analysis for media-literacy purposes. The verdict concerns one extracted claim, not the whole post. Verify against the listed sources."
}
```

### Field guide for rendering

Render in this order. It is the reading order the product is designed around.

| Field | Render as |
| --- | --- |
| `analysis.main_claim` | First block, headed MAIN CLAIM. Show `text` in quotes. `quote` is the span in the post; highlight it in the post preview if you show one. When `found` is false, show "No checkable factual claim in this post" and skip the claim-check block's verdict styling. |
| `analysis.claim_check.verdict` | A pill. `supported` green · `partially_supported` amber · `unsupported` red · `unverifiable` grey · `no_factual_claim` grey. Never label the post itself true or false; the verdict is about the claim only. |
| `analysis.claim_check.explanation` | One or two sentences under the pill. |
| `analysis.claim_check.sources` | Numbered links. Guaranteed to be a subset of `evidence`; the server drops anything the model invented. Empty list is normal for `unverifiable` and `no_factual_claim`. |
| `analysis.missing_context` | Headed MISSING CONTEXT. Empty string means nothing material is missing: hide the block. |
| `analysis.rhetorical_signals[]` | Badges. `name` comes from the canonical list in `backend/prompts/taxonomy.py`; a name starting `Other: ` is uncategorised, render it muted. `evidence` is a verbatim quote from the post: show it under the badge or on hover. Empty list means a plainly informational post; hide the block. |
| `analysis.speaker_context` | Headed SPEAKER CONTEXT. `name · role` on one line, `background` under it. When `background` is exactly `Unknown author`, show that and hide the `sources` list. |
| `evidence[]` | Optional "what we checked against" disclosure. |
| `steps`, `latency_ms`, `model`, `provider`, `cached` | Footer. |
| `disclaimer` | Footer, always visible. |

Suggested layout, matching the product spec:

```
MAIN CLAIM
"Germany accepted 1.2 million migrants last year."

CLAIM CHECK            [ PARTIALLY SUPPORTED ]
The direction is reported by the sources but the scale and timeframe are not.
Sources: [1] Migration report 2025  [2] Fact check…

MISSING CONTEXT
The figure mixes asylum applications with all forms of immigration…

RHETORICAL SIGNALS
[Loaded Language]  "clearly doesn't care about German citizens"

SPEAKER CONTEXT
Example Account
Unknown author
```

## `POST /api/v1/compare`

Runs one post through two to four arms and returns them side by side. Additive to schema v3:
nothing in `AnalyzeResponse` or `PostAnalysis` changes, so `schema_version` stays `"3"`.
The extension does not need this endpoint; it exists for the evaluation story.

Query params: `nocache=true`.

Request is an `/analyze` request plus `variants`. `label` is optional and defaults to
`provider:prompt_version`.

```json
{
  "author_handle": "example_migrants",
  "author_name": "Example Account",
  "post_text": "Germany accepted 1.2M migrants last year. This government clearly doesn't care about German citizens.",
  "variants": [
    { "provider": "nebius", "prompt_version": "v1" },
    { "provider": "gemini", "prompt_version": "v1" }
  ]
}
```

Response, abridged:

```json
{
  "schema_version": "3",
  "post_text": "...",
  "author_handle": "example_migrants",
  "arms": [
    {
      "label": "nebius:v1",
      "provider": "nebius",
      "prompt_version": "v1",
      "model": "openai/gpt-oss-120b",
      "response": { "...": "a complete AnalyzeResponse" },
      "error": null,
      "warnings": []
    },
    {
      "label": "gemini:v1",
      "provider": "gemini",
      "prompt_version": "v1",
      "model": "gemini-2.5-flash",
      "response": null,
      "error": "Gemini timed out after 20s",
      "warnings": []
    }
  ],
  "diff": {
    "claim_agreement": 1.0,
    "verdict_agreement": 1.0,
    "signal_overlap": 0.0,
    "verdicts": { "nebius:v1": "partially_supported", "nebius:v0": "partially_supported" },
    "signals": { "nebius:v1": ["Loaded Language"], "nebius:v0": ["Other: emotive appeal / blame"] },
    "latency_ms": { "nebius:v1": 2493, "nebius:v0": 2155 },
    "cost_usd": { "nebius:v1": 0.00074, "nebius:v0": 0.0006 }
  },
  "evidence": [],
  "total_latency_ms": 4648,
  "total_cost_usd": 0.00134
}
```

Notes for anyone consuming this:

- **Arms run in order, not in parallel.** The Brave cache is keyed on the claim text, so
  concurrent arms would both miss it and spend two live searches. Sequential means one live
  search per compare and every arm judged on the same evidence. Two arms take 4 to 8 s.
- **A failed arm is data, not an error.** `error` is filled, `response` is `null`, and the
  request is still `200`. Only an all-arms failure is a `502`.
- `warnings` carries the same three checks `scripts/check_nebius.py` prints: non-verbatim
  quotes, labels outside `backend/prompts/taxonomy.py`, and cited URLs absent from the evidence.
- The agreement rates are over unordered arm pairs and are `null` when fewer than two arms
  succeeded. `claim_agreement` counts overlapping quoted spans, not string equality.
- `evidence` at the top level is the first successful arm's evidence, which the other arms
  shared.

CLI equivalent, no server needed:

```bash
.venv/bin/python scripts/compare.py --post spec_example --variants nebius:v1,gemini:v1
```

## Two-stage claim picker

`/analyze` above picks the claim itself. The two-stage flow hands that choice to the reader:
stage 1 says what is checkable, the reader picks one, stage 2 checks it. They can come back and
pick another.

Additive: `/analyze` is unchanged and `schema_version` stays `"3"`.

The fields split by scope, which is what makes a second claim cheap:

| Scope | Fields | Endpoint |
| --- | --- | --- |
| Post | `claims[]`, `rhetorical_signals`, `speaker_context`, `sources` | `/claims` |
| Claim | `claim_check`, `missing_context`, `evidence` | `/analyze-claim` |

The author lookup and the signal pass run once, in stage 1. Checking a second claim costs one
search plus one model call.

### `POST /api/v1/claims`

Request: identical to `/analyze`. Query params: `provider`, `prompt_version`, `nocache`.

```json
{
  "schema_version": "3",
  "claims": [
    { "id": "c1", "text": "Germany accepted 1.2 million migrants last year.", "quote": "Germany accepted 1.2M migrants last year." },
    { "id": "c2", "text": "Germany's asylum budget increased in 2025.", "quote": "the asylum budget keeps climbing" }
  ],
  "rhetorical_signals": [
    { "name": "Loaded Language", "evidence": "clearly doesn't care about German citizens" }
  ],
  "speaker_context": { "name": "Example Account", "role": "", "background": "Unknown author" },
  "sources": [],
  "steps": { "extract_ms": 640, "evidence_ms": 0, "analyse_ms": 0 },
  "cached": false, "latency_ms": 680,
  "provider": "fake", "model": "fake-v3", "cost_usd": 0.0,
  "disclaimer": "..."
}
```

No verdict appears here; nothing has been checked yet. `claims: []` means the post carries no
checkable factual claim, which is normal for pure rhetoric: render the signals and speaker
blocks and say so.

`claims` is ordered most central first, capped at `MAX_CLAIMS` (default 4). **Every `quote` is
guaranteed to be a literal substring of `post_text`**: the server snaps it back onto the exact
characters of the post and drops any claim it cannot locate, so the client can always highlight
the span. Ids are `c1`, `c2`, ... and stay sequential after a drop.

### `POST /api/v1/analyze-claim`

Request is the post plus the chosen claim, exactly as stage 1 returned it. Stateless.

```json
{
  "author_handle": "example_migrants",
  "author_name": "Example Account",
  "post_text": "Germany accepted 1.2M migrants last year and the asylum budget keeps climbing. ...",
  "platform": "x",
  "claim": { "id": "c1", "text": "Germany accepted 1.2 million migrants last year.", "quote": "Germany accepted 1.2M migrants last year." }
}
```

```json
{
  "schema_version": "3",
  "claim": { "id": "c1", "text": "...", "quote": "..." },
  "claim_check": {
    "verdict": "partially_supported",
    "explanation": "The direction is reported by the sources but the scale and timeframe in the post are not.",
    "sources": [{ "title": "Migration report 2025", "url": "https://www.bamf.example/report-2025" }]
  },
  "missing_context": "The figure mixes asylum applications with all forms of immigration...",
  "evidence": [{ "title": "...", "url": "...", "snippet": "...", "provider": "brave" }],
  "steps": { "extract_ms": 0, "evidence_ms": 520, "analyse_ms": 1220 },
  "cached": false, "latency_ms": 1760,
  "provider": "nebius", "model": "openai/gpt-oss-120b", "cost_usd": 0.00053,
  "disclaimer": "..."
}
```

`verdict` keeps four of the five values; **`no_factual_claim` is unreachable here**, because the
reader already picked a claim. `claim_check.sources` stays a guaranteed subset of `evidence`.

Returns `422` when `claim.quote` is not present in `post_text`, or when `claim.text` is blank.
Without that check a caller could hand the model arbitrary text and have it checked as though
someone had posted it.

### Rendering

Render stage 1 first, then the verdict under whichever claim is open:

```
MAIN POST          with the open claim's quote highlighted

CHECKABLE CLAIMS   2 claims in this post. Pick one to check it against the web.
  [ "Germany accepted 1.2 million migrants last year."      Check this claim ]
      -> PARTIALLY SUPPORTED
         The direction is reported by the sources but the scale is not.
         [1] Migration report 2025   [2] Fact check...
         MISSING CONTEXT  The figure mixes asylum applications with...
  [ "Germany's asylum budget increased in 2025."            Check this claim ]

RHETORICAL SIGNALS [Loaded Language]  "clearly doesn't care about German citizens"

SPEAKER CONTEXT    Example Account
                   Unknown author
```

The verdict belongs to the claim it sits under. As with `/analyze`, the UI must never label the
post itself true or false.

### Offline coverage

`ANALYZER_PROVIDER=fake` covers every branch with no keys at all, including the evidence step:
the fake carries canned web results so all four verdicts are reachable without `BRAVE_API_KEY`.
A live Brave search always wins when it returns anything.

| Handle | Stage 1 | Stage 2 |
| --- | --- | --- |
| `example_migrants` | 2 claims, 1 signal | `c1` partially_supported, `c2` unsupported |
| `alice_weidel` | 2 claims, 4 signals | `c1` partially_supported, `c2` unverifiable |
| `destatis` | 1 claim, no signals | `c1` supported |
| `example_left_mp` | 0 claims, 3 signals | n/a |
| `troll_account` | 0 claims, 2 signals, unknown author | n/a |

Saved payloads: `tests/fixtures/responses_v3/claims_*.json` and `checked_*.json`.

## `POST /api/v1/analyze-media` (arrives Sunday morning)

Video posts. The server downloads the audio with yt-dlp, transcribes it with SLNG (Deepgram Nova 3, EU region), then runs the same pipeline on the transcript.

Request: `{ "post_url": "...", "author_handle": "...", "author_name": "...", "platform": "x" }`

Response: identical plus a filled `transcript`:

```json
"transcript": { "text": "...", "language": "en", "duration_s": 23.4, "stt_provider": "slng/deepgram-nova-3", "stt_latency_ms": 1650 }
```

Full example: `tests/fixtures/responses_v3/media_example.json`. Expect 8 to 15 s end to end, one response, no streaming. Show three stages on a timer: "Downloading audio" (0 to 4 s), "Transcribing" (4 to 8 s), "Analysing" (8 s+). Videos longer than 60 s return `413`.

## Errors

| Status | Meaning |
| --- | --- |
| 400 | Unknown `provider`, or a `/compare` variant naming an unconfigured provider |
| 413 | Video longer than the limit |
| 422 | Validation error |
| 502 | Model call failed or timed out; download or transcription failed; every `/compare` arm failed |
| 503 | No analyzer configured on the server |

Bodies are `{"detail": "..."}`. Examples in `tests/fixtures/responses_v3/error_*.json`.

## Caching

Identical `(provider, model, prompt_version, handle, text)` within `CACHE_TTL_SECONDS` (default 24 h) returns `cached: true` with `latency_ms: 0`. `?nocache=true` bypasses.
