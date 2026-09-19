// Service worker: proxies analysis requests from content scripts to the backend.
// The Gemini key never touches the browser; only the backend URL is configurable.

const DEFAULT_BACKEND = "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 30_000;

async function getBackendUrl() {
  try {
    const { backendUrl } = await chrome.storage.sync.get("backendUrl");
    return (backendUrl || DEFAULT_BACKEND).replace(/\/+$/, "");
  } catch {
    return DEFAULT_BACKEND;
  }
}

async function analyze(payload) {
  const base = await getBackendUrl();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${base}/api/v1/analyze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = body?.detail || `${res.status} ${res.statusText}`;
      return { ok: false, error: typeof detail === "string" ? detail : JSON.stringify(detail) };
    }
    return { ok: true, data: body };
  } catch (err) {
    const msg = err?.name === "AbortError" ? "Backend timed out" : `Backend unreachable at ${base}`;
    return { ok: false, error: msg };
  } finally {
    clearTimeout(timer);
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "ANALYZE") {
    analyze(message.payload).then(sendResponse);
    return true; // keep the channel open for the async response
  }
  if (message?.type === "GET_BACKEND_URL") {
    getBackendUrl().then((url) => sendResponse({ url }));
    return true;
  }
  return false;
});
