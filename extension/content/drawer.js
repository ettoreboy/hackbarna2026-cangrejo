// The panel. Rendered inside a Shadow DOM attached to <html>, so X's stylesheet cannot
// reach in and ours cannot leak out. Renders schema v2 exactly as docs/API.md specifies.
//
// Exposes window.ContextGuardDrawer. Loaded before content.js (order set in manifest.json);
// both are classic scripts sharing the same window object.

(() => {
  const STYLE = `
    :host { all: initial; }
    * { box-sizing: border-box; }

    .drawer {
      position: fixed; top: 0; left: 0; height: 100vh; width: min(420px, 92vw);
      background: #0b1220; color: #e2e8f0; z-index: 2147483000;
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      box-shadow: 8px 0 32px rgba(0,0,0,.45);
      transform: translateX(-100%); transition: transform 220ms cubic-bezier(.4,0,.2,1);
      display: flex; flex-direction: column;
    }
    .drawer.open { transform: translateX(0); }

    header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 18px; border-bottom: 1px solid #1e293b; flex-shrink: 0;
    }
    header h1 { margin: 0; font-size: 15px; font-weight: 700; letter-spacing: .01em; }
    header button {
      all: unset; cursor: pointer; font-size: 16px; line-height: 1;
      padding: 6px 9px; border-radius: 6px; color: #94a3b8;
    }
    header button:hover { background: #1e293b; color: #fff; }
    header button:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }

    .body { padding: 16px 18px 28px; overflow-y: auto; flex: 1; }

    .muted { color: #94a3b8; }
    .small { font-size: 12px; }
    p { margin: 0; }

    /* the post we are analysing */
    .post {
      background: #131f33; border-radius: 10px; padding: 10px 12px; margin-bottom: 16px;
      font-size: 13px; white-space: pre-wrap; max-height: 130px; overflow: auto;
    }
    .post .who { color: #93c5fd; font-weight: 600; margin-bottom: 4px; }

    section { margin-bottom: 20px; }
    section h2 {
      margin: 0 0 8px; font-size: 11px; font-weight: 700;
      text-transform: uppercase; letter-spacing: .08em; color: #94a3b8;
    }

    .summary { font-size: 14px; color: #f1f5f9; }

    /* manipulation band - the hero element */
    .score { display: flex; align-items: center; gap: 12px; }
    .band {
      font-weight: 700; font-size: 13px; padding: 3px 12px;
      border-radius: 9999px; text-transform: capitalize;
    }
    .band.low    { background: #064e3b; color: #6ee7b7; }
    .band.medium { background: #78350f; color: #fcd34d; }
    .band.high   { background: #7f1d1d; color: #fca5a5; }
    .meter { flex: 1; height: 8px; border-radius: 9999px; background: #1e293b; overflow: hidden; }
    .meter > div { height: 100%; border-radius: 9999px; transition: width 450ms ease; }
    .fill-low { background: #34d399; } .fill-medium { background: #fbbf24; } .fill-high { background: #f87171; }
    .pill {
      display: inline-block; margin-top: 10px; font-size: 12px; font-weight: 600;
      padding: 3px 10px; border-radius: 9999px; background: #312e81; color: #c7d2fe;
    }

    /* signal + fallacy cards */
    .card {
      background: #131f33; border: 1px solid #1e293b; border-radius: 9px;
      padding: 9px 11px; margin-bottom: 7px;
    }
    .card:last-child { margin-bottom: 0; }
    .card .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .label { font-weight: 650; font-size: 13px; color: #e2e8f0; }
    .label.other { color: #94a3b8; font-weight: 500; font-style: italic; }
    .conf { font-size: 11px; color: #64748b; flex-shrink: 0; }
    blockquote {
      margin: 6px 0 0; padding-left: 9px; border-left: 2px solid #3b82f6;
      color: #bfdbfe; font-size: 12.5px; font-style: italic; word-break: break-word;
    }
    .card .desc { margin-top: 5px; font-size: 12px; color: #94a3b8; }
    .empty { font-size: 12.5px; color: #64748b; font-style: italic; }

    .sources ul { margin: 0; padding-left: 18px; }
    .sources li { margin-bottom: 5px; font-size: 13px; }
    .sources a { color: #93c5fd; text-decoration: none; }
    .sources a:hover { text-decoration: underline; }

    /* loading + error */
    .loading { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 46px 0; text-align: center; }
    .spinner {
      width: 34px; height: 34px; border: 3px solid #1e293b;
      border-top-color: #60a5fa; border-radius: 50%; animation: spin .9s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) {
      .spinner { animation-duration: 2.4s; }
      .drawer { transition: none; }
    }
    .error { background: #450a0a; border: 1px solid #7f1d1d; color: #fecaca; border-radius: 10px; padding: 12px 14px; }

    footer {
      padding: 10px 18px; border-top: 1px solid #1e293b;
      font-size: 11px; line-height: 1.45; color: #64748b; flex-shrink: 0;
    }
  `;

  // Every value that reaches innerHTML goes through this. Post text is written by a
  // stranger and the model output is influenced by it, so neither is ever trusted.
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const NO_TIMING = "no timing signal identified";
  const UNKNOWN_AUTHOR = "unknown author";
  const norm = (s) => String(s ?? "").trim().replace(/\.$/, "").toLowerCase();

  class ContextGuardDrawer {
    constructor() {
      this.host = null;
      this.root = null;
      this.drawer = null;
      this.body = null;
      this.footer = null;
      this.lastFocus = null;
      this._onKey = (e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          this.close();
        }
      };
    }

    // Built once, on first open, then reused for every subsequent post.
    _ensure() {
      if (this.host) return;
      this.host = document.createElement("div");
      this.host.id = "cg-root";
      document.documentElement.appendChild(this.host);
      this.root = this.host.attachShadow({ mode: "open" });
      this.root.innerHTML = `
        <style>${STYLE}</style>
        <aside class="drawer" role="dialog" aria-modal="false" aria-label="ContextGuard analysis">
          <header>
            <h1>&#128737;&#65039; ContextGuard</h1>
            <button type="button" aria-label="Close panel" data-close>&#10005;</button>
          </header>
          <div class="body"></div>
          <footer></footer>
        </aside>`;
      this.drawer = this.root.querySelector(".drawer");
      this.body = this.root.querySelector(".body");
      this.footer = this.root.querySelector("footer");
      this.root.querySelector("[data-close]").addEventListener("click", () => this.close());
    }

    open(trigger) {
      this._ensure();
      if (trigger) this.lastFocus = trigger;
      requestAnimationFrame(() => this.drawer.classList.add("open"));
      document.addEventListener("keydown", this._onKey, true);
    }

    close() {
      if (!this.drawer) return;
      this.drawer.classList.remove("open");
      document.removeEventListener("keydown", this._onKey, true);
      // Send focus back to the button that opened us, so keyboard users keep their place.
      if (this.lastFocus && document.contains(this.lastFocus)) this.lastFocus.focus();
      this.lastFocus = null;
    }

    // ---------------------------------------------------------------- states

    showLoading(payload, trigger) {
      this.open(trigger);
      this.footer.textContent = "";
      this.body.innerHTML = `
        ${this._postBlock(payload)}
        <div class="loading">
          <div class="spinner"></div>
          <div>Reading the post&hellip;</div>
          <div class="muted small">Looking up the author, then analysing how the post is built.</div>
        </div>`;
    }

    showError(message, trigger) {
      this.open(trigger);
      this.footer.textContent = "";
      this.body.innerHTML = `
        <div class="error"><strong>Analysis failed.</strong><br>${esc(message)}</div>
        <p class="muted small" style="margin-top:12px">
          Is the backend running? Default is http://127.0.0.1:8000 &mdash; check with
          <code>/api/v1/health</code>.
        </p>`;
    }

    showResult(data, payload, trigger) {
      this.open(trigger);

      const a = data.analysis || {};
      const ind = a.indicators || {};
      const band = data.score_band || "medium";
      const score = Math.max(0, Math.min(100, Number(a.manipulation_score ?? 0)));
      const unknownAuthor = norm(a.author_background) === UNKNOWN_AUTHOR;

      this.body.innerHTML = `
        ${this._postBlock(payload)}
        ${this._summary(a)}
        ${this._score(band, score, ind)}
        ${this._author(a, unknownAuthor)}
        ${this._signals(a.communication_signals)}
        ${this._fallacies(a.logical_fallacies)}
        ${this._intent(ind)}
        ${this._lesson(a)}
        ${unknownAuthor ? "" : this._sources(data.sources)}
      `;
      this.body.scrollTop = 0;
      this.footer.innerHTML = this._footer(data);
    }

    // ---------------------------------------------------------------- sections

    _postBlock(payload) {
      if (!payload) return "";
      return `<div class="post">
        <div class="who">${esc(payload.author_name)} <span class="muted">@${esc(payload.author_handle)}</span></div>
        ${esc(payload.post_text)}
      </div>`;
    }

    _summary(a) {
      if (!a.post_summary) return "";
      return `<section>
        <h2>What this post says</h2>
        <p class="summary">${esc(a.post_summary)}</p>
      </section>`;
    }

    _score(band, score, ind) {
      return `<section>
        <h2>Manipulation level</h2>
        <div class="score">
          <span class="band ${esc(band)}">${esc(band)}</span>
          <div class="meter"><div class="fill-${esc(band)}" style="width:${Math.max(2, score)}%"></div></div>
          <span class="muted small">${score}/100</span>
        </div>
        ${ind.is_division_tactic ? `<span class="pill">Built to divide</span>` : ""}
      </section>`;
    }

    _author(a, unknownAuthor) {
      if (unknownAuthor) {
        return `<section>
          <h2>Author</h2>
          <p><strong>${esc(a.author)}</strong></p>
          <p class="muted small">Unknown author &mdash; no public background found, so nothing here is
          verified about who is speaking.</p>
        </section>`;
      }
      return `<section>
        <h2>Author</h2>
        <p><strong>${esc(a.author)}</strong></p>
        <p class="muted">${esc(a.author_background)}</p>
      </section>`;
    }

    _signals(signals) {
      const list = (signals || []).filter((s) => !window.CG_TAXONOMY.shouldHideSignal(s));
      if (!list.length) {
        return `<section>
          <h2>Communication signals</h2>
          <p class="empty">No persuasion signals identified. Reads as informational.</p>
        </section>`;
      }
      const cards = list
        .map((s) => {
          const other = window.CG_TAXONOMY.isUncategorised(s.name);
          const pct = Math.round(Number(s.confidence ?? 0) * 100);
          return `<div class="card">
            <div class="top">
              <span class="label ${other ? "other" : ""}">${esc(s.name)}</span>
              <span class="conf">${pct}% confident</span>
            </div>
            ${s.evidence ? `<blockquote>&ldquo;${esc(s.evidence)}&rdquo;</blockquote>` : ""}
            ${s.description ? `<p class="desc">${esc(s.description)}</p>` : ""}
          </div>`;
        })
        .join("");
      return `<section><h2>Communication signals</h2>${cards}</section>`;
    }

    _fallacies(fallacies) {
      const list = fallacies || [];
      if (!list.length) return "";
      const cards = list
        .map((f) => {
          const other = window.CG_TAXONOMY.isUncategorised(f.name);
          return `<div class="card">
            <div class="top"><span class="label ${other ? "other" : ""}">${esc(f.name)}</span></div>
            ${f.evidence ? `<blockquote>&ldquo;${esc(f.evidence)}&rdquo;</blockquote>` : ""}
          </div>`;
        })
        .join("");
      return `<section><h2>Logical fallacies</h2>${cards}</section>`;
    }

    _intent(ind) {
      if (!ind.strategic_intent && !ind.factual_context) return "";
      const showTiming = ind.timing_note && norm(ind.timing_note) !== NO_TIMING;
      return `<section>
        <h2>Why post this, now</h2>
        ${ind.strategic_intent ? `<p>${esc(ind.strategic_intent)}</p>` : ""}
        ${showTiming ? `<p class="muted small" style="margin-top:6px">${esc(ind.timing_note)}</p>` : ""}
        ${
          ind.factual_context
            ? `<p class="muted" style="margin-top:10px">${esc(ind.factual_context)}</p>`
            : ""
        }
      </section>`;
    }

    _lesson(a) {
      if (!a.cognitive_summary) return "";
      return `<section>
        <h2>Pattern to remember</h2>
        <p>${esc(a.cognitive_summary)}</p>
      </section>`;
    }

    _sources(sources) {
      const list = sources || [];
      if (!list.length) {
        return `<section class="sources">
          <h2>Sources</h2>
          <p class="empty">No background source found. The description above is only what the model already knew.</p>
        </section>`;
      }
      const items = list
        .map(
          (s) => `<li>
            <a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>
            <span class="muted small">(${esc(s.provider)})</span>
          </li>`
        )
        .join("");
      return `<section class="sources"><h2>Sources</h2><ul>${items}</ul></section>`;
    }

    _footer(data) {
      const timing = data.cached ? "cached" : `${data.latency_ms} ms`;
      const meta = [data.provider, data.model, timing].filter(Boolean).map(esc).join(" &middot; ");
      return `${esc(data.disclaimer || "")}<br><span style="opacity:.75">${meta}</span>`;
    }
  }

  window.ContextGuardDrawer = ContextGuardDrawer;
})();
