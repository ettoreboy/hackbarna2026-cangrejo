// Left-side drawer rendered in a Shadow DOM so X's styles cannot bleed in or out.
// Exposes window.ContextGuardOverlay for content.js (both are classic scripts, load order set in manifest).

(() => {
  const STYLE = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .drawer {
      position: fixed; top: 0; left: 0; height: 100vh; width: min(420px, 92vw);
      background: #0f172a; color: #e2e8f0; z-index: 2147483000;
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      box-shadow: 8px 0 32px rgba(0,0,0,.35);
      transform: translateX(-100%); transition: transform 200ms ease;
      display: flex; flex-direction: column;
    }
    .drawer.open { transform: translateX(0); }
    header { display:flex; align-items:center; justify-content:space-between; padding: 14px 18px; border-bottom: 1px solid #1e293b; }
    header h1 { margin:0; font-size: 15px; font-weight: 700; letter-spacing: .01em; }
    header button { all: unset; cursor: pointer; font-size: 18px; padding: 4px 8px; border-radius: 6px; color:#94a3b8; }
    header button:hover { background:#1e293b; color:#fff; }
    .body { padding: 16px 18px 28px; overflow-y: auto; flex: 1; }
    .muted { color: #94a3b8; }
    .small { font-size: 12px; }
    .post { background:#1e293b; border-radius: 10px; padding: 10px 12px; margin-bottom: 16px; font-size: 13px; white-space: pre-wrap; max-height: 120px; overflow:auto; }
    .post .who { color:#93c5fd; font-weight:600; margin-bottom:4px; }
    section { margin-bottom: 18px; }
    section h2 { margin: 0 0 6px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #94a3b8; }
    .score { display:flex; align-items:center; gap: 12px; }
    .meter { flex:1; height: 8px; border-radius: 9999px; background:#1e293b; overflow:hidden; }
    .meter > div { height:100%; border-radius: 9999px; transition: width 400ms ease; }
    .band { font-weight: 700; font-size: 13px; padding: 2px 10px; border-radius: 9999px; text-transform: capitalize; }
    .band.low { background:#064e3b; color:#6ee7b7; }
    .band.medium { background:#78350f; color:#fcd34d; }
    .band.high { background:#7f1d1d; color:#fca5a5; }
    .low-fill { background:#34d399; } .medium-fill { background:#fbbf24; } .high-fill { background:#f87171; }
    .pill { display:inline-block; margin-top:8px; font-size: 12px; padding: 3px 10px; border-radius: 9999px; background:#312e81; color:#c7d2fe; }
    .tags { display:flex; flex-wrap:wrap; gap: 6px; }
    .tag { position:relative; background:#1e293b; border:1px solid #334155; border-radius: 8px; padding: 4px 10px; font-size: 12px; cursor: help; }
    .tag.fallacy { border-color:#475569; color:#cbd5e1; }
    .tag .tip { display:none; position:absolute; left:0; top: calc(100% + 6px); width: 260px; background:#020617; border:1px solid #334155; border-radius:8px; padding:8px 10px; font-size:12px; z-index: 2; color:#e2e8f0; }
    .tag:hover .tip { display:block; }
    p { margin: 0; }
    .sources a { color:#93c5fd; text-decoration:none; word-break: break-all; }
    .sources li { margin-bottom: 4px; }
    .sources ul { margin: 0; padding-left: 18px; }
    .loading { display:flex; flex-direction:column; align-items:center; gap: 14px; padding: 48px 0; text-align:center; }
    .spinner { width: 36px; height: 36px; border: 3px solid #1e293b; border-top-color:#60a5fa; border-radius:50%; animation: spin .9s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .error { background:#7f1d1d; color:#fecaca; border-radius: 10px; padding: 12px 14px; }
    footer { padding: 10px 18px; border-top: 1px solid #1e293b; font-size: 11px; color:#64748b; }
  `;

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  class ContextGuardOverlay {
    constructor() {
      this.host = null;
      this.root = null;
      this.drawer = null;
      this.body = null;
      this.footer = null;
      this._onKey = (e) => { if (e.key === "Escape") this.close(); };
    }

    _ensure() {
      if (this.host) return;
      this.host = document.createElement("div");
      this.host.id = "cg-root";
      document.documentElement.appendChild(this.host);
      this.root = this.host.attachShadow({ mode: "open" });
      this.root.innerHTML = `
        <style>${STYLE}</style>
        <aside class="drawer" role="dialog" aria-label="ContextGuard analysis">
          <header>
            <h1>🛡️ ContextGuard</h1>
            <button type="button" aria-label="Close" data-close>✕</button>
          </header>
          <div class="body"></div>
          <footer></footer>
        </aside>`;
      this.drawer = this.root.querySelector(".drawer");
      this.body = this.root.querySelector(".body");
      this.footer = this.root.querySelector("footer");
      this.root.querySelector("[data-close]").addEventListener("click", () => this.close());
    }

    open() {
      this._ensure();
      requestAnimationFrame(() => this.drawer.classList.add("open"));
      document.addEventListener("keydown", this._onKey);
    }

    close() {
      if (!this.drawer) return;
      this.drawer.classList.remove("open");
      document.removeEventListener("keydown", this._onKey);
    }

    _postBlock(payload) {
      if (!payload) return "";
      return `<div class="post"><div class="who">${esc(payload.author_name)} <span class="muted">@${esc(payload.author_handle)}</span></div>${esc(payload.post_text)}</div>`;
    }

    showLoading(payload) {
      this.open();
      this.footer.textContent = "";
      this.body.innerHTML = `${this._postBlock(payload)}
        <div class="loading">
          <div class="spinner"></div>
          <div>Unpacking political context &amp; manipulation tactics…</div>
          <div class="muted small">Looking up author background, then asking Gemini Flash.</div>
        </div>`;
    }

    showError(message) {
      this.open();
      this.body.innerHTML = `<div class="error"><strong>Analysis failed.</strong><br>${esc(message)}</div>
        <p class="muted small" style="margin-top:12px">Is the backend running? Default: http://127.0.0.1:8000</p>`;
    }

    showResult(data, payload) {
      this.open();
      const a = data.analysis || {};
      const band = data.score_band || "medium";
      const score = Number(a.manipulation_score ?? 0);

      const tactics = (a.tactics_detected || [])
        .map((t) => `<span class="tag">${esc(t.name)}<span class="tip">${esc(t.description)}</span></span>`)
        .join("");
      const fallacies = (a.logical_fallacies || []).map((f) => `<span class="tag fallacy">${esc(f)}</span>`).join("");
      const sources = (data.sources || [])
        .map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a> <span class="muted small">(${esc(s.provider)})</span></li>`)
        .join("");

      this.body.innerHTML = `
        ${this._postBlock(payload)}
        <section>
          <h2>Manipulation level</h2>
          <div class="score">
            <span class="band ${band}">${band}</span>
            <div class="meter"><div class="${band}-fill" style="width:${Math.max(2, Math.min(100, score))}%"></div></div>
            <span class="muted small">${score}/100</span>
          </div>
          ${a.is_division_tactic ? `<span class="pill">Built to divide in-group vs out-group</span>` : ""}
        </section>
        <section>
          <h2>Author</h2>
          <p><strong>${esc(a.author)}</strong></p>
          <p class="muted">${esc(a.author_background)}</p>
        </section>
        ${tactics ? `<section><h2>Tactics detected</h2><div class="tags">${tactics}</div><p class="muted small" style="margin-top:6px">Hover a tag to see how it is used here.</p></section>` : ""}
        ${fallacies ? `<section><h2>Logical fallacies</h2><div class="tags">${fallacies}</div></section>` : ""}
        <section><h2>Strategic intent</h2><p>${esc(a.strategic_intent)}</p></section>
        <section><h2>Factual context</h2><p>${esc(a.factual_context)}</p></section>
        <section><h2>Pattern to remember</h2><p>${esc(a.cognitive_summary)}</p></section>
        ${sources ? `<section class="sources"><h2>Sources</h2><ul>${sources}</ul></section>` : `<section class="sources"><h2>Sources</h2><p class="muted small">No background source found. Biography above is limited to what the model already knows.</p></section>`}
      `;
      this.footer.textContent = `${data.disclaimer || ""} ${data.cached ? "· cached" : `· ${data.latency_ms} ms`} · ${data.model || ""}`;
    }
  }

  window.ContextGuardOverlay = ContextGuardOverlay;
})();
