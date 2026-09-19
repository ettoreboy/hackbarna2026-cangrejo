// Service worker. The only part of the extension that talks to the network.
//
// Why this file exists: a fetch from a content script runs with x.com's origin and is
// subject to X's Content-Security-Policy, which blocks calls to localhost. A fetch from
// here runs with origin chrome-extension://<id>, which the backend's CORS allows.
//
// No API keys ever live in the browser. The backend holds all of them.

const DEFAULT_BACKEND = "http://127.0.0.1:8000";
const TIMEOUT_TEXT_MS = 30_000;
const TIMEOUT_MEDIA_MS = 45_000; // download + transcribe + analyse

// Point at a teammate's machine from the service worker console:
//   chrome.storage.sync.set({ backendUrl: "http://192.168.1.42:8000" })
async function getBackendUrl() {
  try {
    const { backendUrl } = await chrome.storage.sync.get("backendUrl");
    return (backendUrl || DEFAULT_BACKEND).replace(/\/+$/, "");
  } catch {
    return DEFAULT_BACKEND;
  }
}

async function postJson(path, payload, timeoutMs) {
  const base = await getBackendUrl();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      if (res.status === 404) {
        return { ok: false, error: `${path} is not available on the backend yet.` };
      }
      if (res.status === 413) {
        return { ok: false, error: "Videos over 60 s are not supported yet." };
      }
      const detail = body && body.detail;
      return {
        ok: false,
        error: typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `${res.status} ${res.statusText}`,
      };
    }

    return { ok: true, data: body };
  } catch (err) {
    const msg =
      err && err.name === "AbortError"
        ? "Backend timed out."
        : `Backend unreachable at ${base}. Is uvicorn running?`;
    return { ok: false, error: msg };
  } finally {
    clearTimeout(timer);
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const type = message && message.type;

  // Two-stage flow: find the claims, then check the one the reader picked.
  if (type === "CLAIMS") {
    postJson("/api/v1/claims", message.payload, TIMEOUT_TEXT_MS).then(sendResponse);
    return true; // keeps the message channel open for the async reply
  }

  if (type === "ANALYZE_CLAIM") {
    postJson("/api/v1/analyze-claim", message.payload, TIMEOUT_TEXT_MS).then(sendResponse);
    return true;
  }

  // One-shot pipeline, kept as a fallback.
  if (type === "ANALYZE") {
    postJson("/api/v1/analyze", message.payload, TIMEOUT_TEXT_MS).then(sendResponse);
    return true;
  }

  if (type === "ANALYZE_MEDIA") {
    postJson("/api/v1/analyze-media", message.payload, TIMEOUT_MEDIA_MS).then(sendResponse);
    return true;
  }

  if (type === "GET_BACKEND_URL") {
    getBackendUrl().then((url) => sendResponse({ url }));
    return true;
  }

  return false;
});
