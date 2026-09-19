// The panel. Rendered inside a Shadow DOM attached to <html>, so X's stylesheet cannot
// reach in and ours cannot leak out. Renders schema v3 (claim-first) per docs/API.md.
//
// Reading order is fixed by the product spec and must not be reshuffled:
//   MAIN CLAIM -> CLAIM CHECK -> MISSING CONTEXT -> RHETORICAL SIGNALS -> SPEAKER CONTEXT
//
// The verdict describes the extracted claim, never the post. Nothing here may call a
// post true, false or fake.
//
// Exposes window.ContextGuardDrawer. Loaded after taxonomy.js and before content.js
// (order set in manifest.json); all three are classic scripts sharing window.

(() => {
  const STYLE = `
    :host { all: initial; }
    * { box-sizing: border-box; }

    .drawer {
      position: fixed; top: 0; left: 0; height: 100vh; width: min(430px, 92vw);
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

    /* the post being analysed, with the claim span highlighted */
    .post {
      background: #131f33; border-radius: 10px; padding: 10px 12px; margin-bottom: 18px;
      font-size: 13px; white-space: pre-wrap; max-height: 130px; overflow: auto;
    }
    .post .who { color: #93c5fd; font-weight: 600; margin-bottom: 4px; }
    .post mark {
      background: rgba(96,165,250,.22); color: #dbeafe;
      border-bottom: 1px solid #60a5fa; border-radius: 2px; padding: 0 1px;
    }

    section { margin-bottom: 20px; }
    section h2 {
      margin: 0 0 8px; font-size: 11px; font-weight: 700;
      text-transform: uppercase; letter-spacing: .08em; color: #94a3b8;
    }

    /* main claim */
    .claim {
      font-size: 15px; line-height: 1.5; color: #f1f5f9;
      border-left: 3px solid #3b82f6; padding-left: 11px;
    }
    .claim.none { border-left-color: #475569; color: #94a3b8; font-size: 14px; font-style: italic; }

    /* verdict pill */
    .verdict-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
    .pill {
      font-weight: 700; font-size: 12px; letter-spacing: .03em; text-transform: uppercase;
      padding: 4px 12px; border-radius: 9999px; white-space: nowrap;
    }
    .pill.green { background: #064e3b; color: #6ee7b7; }
    .pill.amber { background: #78350f; color: #fcd34d; }
    .pill.red   { background: #7f1d1d; color: #fca5a5; }
    .pill.grey  { background: #1e293b; color: #cbd5e1; }

    .cite-list { margin: 9px 0 0; padding: 0; list-style: none; font-size: 12.5px; }
    .cite-list li { margin-bottom: 4px; display: flex; gap: 6px; }
    .cite-n { color: #64748b; flex-shrink: 0; }
    a { color: #93c5fd; text-decoration: none; word-break: break-word; }
    a:hover { text-decoration: underline; }

    /* signals */
    .signal {
      background: #131f33; border: 1px solid #1e293b; border-radius: 9px;
      padding: 9px 11px; margin-bottom: 7px;
    }
    .signal:last-child { margin-bottom: 0; }
    .label { font-weight: 650; font-size: 13px; color: #e2e8f0; }
    .label.other { color: #94a3b8; font-weight: 500; font-style: italic; }
    .caution { font-size: 10.5px; color: #64748b; margin-left: 7px; font-weight: 400; text-transform: none; }
    blockquote {
      margin: 6px 0 0; padding-left: 9px; border-left: 2px solid #3b82f6;
      color: #bfdbfe; font-size: 12.5px; font-style: italic; word-break: break-word;
    }

    /* evidence disclosure */
    details { border-top: 1px solid #1e293b; padding-top: 12px; }
    summary { cursor: pointer; font-size: 12px; color: #94a3b8; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    summary::before { content: "\\25B8 "; color: #64748b; }
    details[open] summary::before { content: "\\25BE "; }
    .ev { margin-top: 9px; font-size: 12.5px; }
    .ev li { margin-bottom: 8px; }
    .ev ul { margin: 0; padding-left: 16px; }
    .ev .snip { color: #64748b; font-size: 12px; }

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

  // Everything that reaches innerHTML goes through this. The post is written by a stranger
  // and the model output is influenced by it, so neither is ever trusted.
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

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
          <div>Finding the claim&hellip;</div>
          <div class="muted small">Extracting the main factual claim, then checking it against the web.</div>
        </div>`;
    }

    showError(message, trigger) {
      this.open(trigger);
      this.footer.textContent = "";
      this.body.innerHTML = `
        <div class="error"><strong>Analysis failed.</strong><br>${esc(message)}</div>
        <p class="muted small" style="margin-top:12px">
          Is the backend running? Default is http://127.0.0.1:8000 &mdash; check
          <code>/api/v1/health</code>.
        </p>`;
    }

    showResult(data, payload, trigger) {
      this.open(trigger);

      const a = data.analysis || {};
      const claim = a.main_claim || {};
      const check = a.claim_check || {};
      const speaker = a.speaker_context || {};
      const unknownAuthor = norm(speaker.background) === UNKNOWN_AUTHOR;

      this.body.innerHTML = `
        ${this._postBlock(payload, claim)}
        ${this._claim(claim)}
        ${this._check(check, claim)}
        ${this._missingContext(a.missing_context)}
        ${this._signals(a.rhetorical_signals)}
        ${this._speaker(speaker, unknownAuthor, data.sources)}
        ${this._evidence(data.evidence)}
      `;
      this.body.scrollTop = 0;
      this.footer.innerHTML = this._footer(data);
    }

    // ---------------------------------------------------------------- blocks

    // Highlights the claim's verbatim span inside the post, so the reader can see exactly
    // which words were checked. Escape first, then wrap - never the other way round.
    _postBlock(payload, claim) {
      if (!payload) return "";
      let text = esc(payload.post_text);
      const quote = claim && claim.found ? esc(claim.quote || "") : "";
      if (quote && text.includes(quote)) {
        text = text.split(quote).join(`<mark>${quote}</mark>`);
      }
      return `<div class="post">
        <div class="who">${esc(payload.author_name)} <span class="muted">@${esc(payload.author_handle)}</span></div>
        ${text}
      </div>`;
    }

    _claim(claim) {
      if (!claim.found) {
        return `<section>
          <h2>Main claim</h2>
          <p class="claim none">No checkable factual claim in this post.</p>
        </section>`;
      }
      return `<section>
        <h2>Main claim</h2>
        <p class="claim">&ldquo;${esc(claim.text)}&rdquo;</p>
      </section>`;
    }

    _check(check, claim) {
      const v = window.CG_TAXONOMY.verdict(check.verdict);
      const sources = check.sources || [];
      const cites = sources.length
        ? `<ul class="cite-list">${sources
            .map(
              (s, i) => `<li>
                <span class="cite-n">[${i + 1}]</span>
                <a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>
              </li>`
            )
            .join("")}</ul>`
        : "";

      return `<section>
        <h2>Claim check</h2>
        <div class="verdict-row">
          <span class="pill ${v.tone}">${esc(v.label)}</span>
          ${claim.found ? "" : `<span class="muted small">nothing to verify</span>`}
        </div>
        ${check.explanation ? `<p>${esc(check.explanation)}</p>` : ""}
        ${cites}
      </section>`;
    }

    // Empty string means nothing material is missing: hide the block entirely.
    _missingContext(text) {
      if (!text || !String(text).trim()) return "";
      return `<section>
        <h2>Missing context</h2>
        <p>${esc(text)}</p>
      </section>`;
    }

    // Empty list means a plainly informational post: hide the block entirely.
    _signals(signals) {
      const list = signals || [];
      if (!list.length) return "";
      const cards = list
        .map((s) => {
          const other = window.CG_TAXONOMY.isUncategorised(s.name);
          const risky = window.CG_TAXONOMY.isHighRisk(s.name);
          return `<div class="signal">
            <span class="label ${other ? "other" : ""}">${esc(s.name)}</span>
            ${risky ? `<span class="caution">flagged cautiously</span>` : ""}
            ${s.evidence ? `<blockquote>&ldquo;${esc(s.evidence)}&rdquo;</blockquote>` : ""}
          </div>`;
        })
        .join("");
      return `<section><h2>Rhetorical signals</h2>${cards}</section>`;
    }

    _speaker(speaker, unknownAuthor, sources) {
      const nameLine = [speaker.name, speaker.role].filter((s) => s && String(s).trim()).map(esc).join(" &middot; ");
      if (unknownAuthor) {
        return `<section>
          <h2>Speaker context</h2>
          <p><strong>${nameLine}</strong></p>
          <p class="muted small">Unknown author &mdash; no public background found, so nothing is
          verified about who is speaking.</p>
        </section>`;
      }
      const list = sources || [];
      const links = list.length
        ? `<ul class="cite-list" style="margin-top:8px">${list
            .map(
              (s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>
                <span class="muted">(${esc(s.provider)})</span></li>`
            )
            .join("")}</ul>`
        : "";
      return `<section>
        <h2>Speaker context</h2>
        <p><strong>${nameLine}</strong></p>
        ${speaker.background ? `<p class="muted" style="margin-top:4px">${esc(speaker.background)}</p>` : ""}
        ${links}
      </section>`;
    }

    // Optional "what we checked against" disclosure.
    _evidence(evidence) {
      const list = evidence || [];
      if (!list.length) return "";
      const items = list
        .map(
          (e) => `<li>
            <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)}</a>
            ${e.snippet ? `<div class="snip">${esc(e.snippet)}</div>` : ""}
          </li>`
        )
        .join("");
      return `<details>
        <summary>What the claim was checked against (${list.length})</summary>
        <div class="ev"><ul>${items}</ul></div>
      </details>`;
    }

    _footer(data) {
      const s = data.steps || {};
      const timing = data.cached ? "cached" : `${data.latency_ms} ms`;
      const meta = [data.provider, data.model, timing].filter(Boolean).map((x) => esc(x)).join(" &middot; ");
      const steps =
        !data.cached && (s.extract_ms || s.evidence_ms || s.analyse_ms)
          ? `<br><span style="opacity:.6">claim ${s.extract_ms || 0} ms &middot; evidence ${
              s.evidence_ms || 0
            } ms &middot; analysis ${s.analyse_ms || 0} ms</span>`
          : "";
      return `${esc(data.disclaimer || "")}<br><span style="opacity:.75">${meta}</span>${steps}`;
    }
  }

  window.ContextGuardDrawer = ContextGuardDrawer;
})();
