# API contract (schema v2)

Base URL in development: `http://127.0.0.1:8000`. Live OpenAPI: `/docs`.

CORS allows origins `chrome-extension://<32 lowercase letters>` and `http(s)://localhost` / `127.0.0.1` on any port. Only `content-type` may be sent as a custom header.

## Offline mode

```bash
ANALYZER_PROVIDER=fake uvicorn backend.main:app --reload
```

Returns deterministic v2 responses with no API keys. Handles `Alice_Weidel` (high), `example_centrist` (medium), `destatis` (low), `troll_account` (unknown author) hit specific fixtures; any other handle gets the high profile. The same payloads are saved in `tests/fixtures/responses_v2/`.

## `GET /api/v1/health`

```json
{ "status": "ok", "schema_version": "2", "providers": ["fake"], "default_provider": "fake", "brave_configured": false, "slng_configured": false }
```

## `POST /api/v1/analyze`

Text posts. Query params, all optional: `provider=nebius|gemini|fake`, `prompt_version=v0|v1`, `nocache=true`.

Request:

```json
{
  "author_handle": "Alice_Weidel",
  "author_name": "Alice Weidel",
  "post_text": "Every day more illegal migrants pour over our borders ...",
  "platform": "x",
  "post_url": "https://x.com/Alice_Weidel/status/1000000000000000001"
}
```

`author_handle` may carry a leading `@`; the server strips it. `post_text` 1–8000 chars. `post_url` optional.

Response (`tests/fixtures/responses_v2/text_high.json` is the full example):

```json
{
  "schema_version": "2",
  "analysis": {
    "post_summary": "The author links a social problem to one group and demands an immediate binary choice.",
    "author": "Alice Weidel",
    "author_background": "Alice Elisabeth Weidel is a German politician who has served as co-leader of ...",
    "communication_signals": [
      { "name": "Outrage Farming", "evidence": "pour over our borders", "confidence": 0.85, "description": "Emotionally charged imagery chosen to trigger sharing." },
      { "name": "Scapegoating", "evidence": "illegal migrants", "confidence": 0.9, "description": "Attributes a complex problem to one group as the sole cause." }
    ],
    "logical_fallacies": [
      { "name": "False Dilemma", "evidence": "Either we" }
    ],
    "indicators": {
      "strategic_intent": "Mobilize the base by naming a culprit and a deadline.",
      "timing_note": "No timing signal identified.",
      "factual_context": "The causal link asserted is not supported by any cited data.",
      "is_division_tactic": true
    },
    "manipulation_score": 85,
    "cognitive_summary": "Culprit plus deadline plus binary choice is the standard mobilisation triad. ..."
  },
  "score_band": "high",
  "sources": [
    { "title": "Alice Weidel", "url": "https://en.wikipedia.org/wiki/Alice_Weidel", "snippet": "...", "provider": "wikipedia" }
  ],
  "transcript": null,
  "cached": false,
  "latency_ms": 2840,
  "provider": "nebius",
  "model": "Qwen/Qwen3-235B-A22B-Instruct-2507",
  "cost_usd": 0.0011,
  "disclaimer": "AI-generated analysis for media-literacy purposes. Not a fact-check. Verify claims against the listed sources."
}
```

### Field guide for rendering

| Field | Render as |
| --- | --- |
| `analysis.post_summary` | First line of the result, plain text |
| `score_band` | The prominent element: `low` green, `medium` amber, `high` red. Show `manipulation_score` small next to it. |
| `analysis.communication_signals[]` | Badges. `name` is from the canonical list in `backend/prompts/taxonomy.py`; a name starting with `Other: ` is uncategorised, render it muted. `evidence` is a verbatim quote from the post, show it under or on hover of the badge. Hide the badge when `name` is one of Dog Whistle, Scapegoating, Dehumanization **and** `confidence < 0.6`. |
| `analysis.logical_fallacies[]` | Chips with `evidence` on hover. |
| `analysis.indicators.is_division_tactic` | A pill "Built to divide" when true. |
| `analysis.indicators.timing_note` | Small line under strategic intent. Skip when it equals `No timing signal identified`. |
| `analysis.author_background` | Author box. If exactly `Unknown author`, say so and hide the sources section. |
| `sources[]` | Links with provider tag. |
| `cached`, `latency_ms`, `model`, `provider` | Footer. |
| `disclaimer` | Footer, always visible. |

## `POST /api/v1/analyze-media` (available Saturday night)

Video posts. The server downloads the audio with yt-dlp, transcribes with SLNG (Deepgram Nova 3, EU region), then runs the same analysis on the transcript.

Request:

```json
{ "post_url": "https://x.com/someone/status/1234567890", "author_handle": "someone", "author_name": "Some One", "platform": "x" }
```

Response: identical to `/analyze` plus a filled `transcript`:

```json
"transcript": { "text": "...", "language": "en", "duration_s": 23.4, "stt_provider": "slng/deepgram-nova-3", "stt_latency_ms": 1650 }
```

Full example: `tests/fixtures/responses_v2/media_example.json`. Expect 8–15 s end to end. The server returns one response, no streaming. Client should show three stages on a timer: "Downloading audio" (0–4 s), "Transcribing" (4–8 s), "Analysing" (8 s+). Videos longer than 60 s return `413`.

Until the endpoint ships, `ANALYZER_PROVIDER=fake` will serve `/analyze-media` with the fixture transcript so the client path can be built.

## Errors

| Status | Meaning | Body |
| --- | --- | --- |
| 400 | Unknown `provider` | `{"detail": "Unknown or unconfigured provider 'x'. Available: [...]"}` |
| 413 | Video longer than the limit | `{"detail": "..."}` |
| 422 | Validation error | FastAPI default |
| 502 | Model call failed, timed out, download or transcription failed | `{"detail": "..."}` |
| 503 | No analyzer configured on the server | `{"detail": "..."}` |

Examples in `tests/fixtures/responses_v2/error_*.json`.

## Caching

Identical `(provider, model, prompt_version, handle, text)` within `CACHE_TTL_SECONDS` (default 24 h) returns `cached: true` with `latency_ms: 0`. `?nocache=true` bypasses.
