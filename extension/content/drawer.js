// The panel. Rendered inside a Shadow DOM attached to <html>, so X's stylesheet cannot
// reach in and ours cannot leak out.
//
// Two-stage flow:
//   stage 1  POST /api/v1/claims        what is checkable, how it is written, who is speaking
//   ...the reader picks a claim...
//   stage 2  POST /api/v1/analyze-claim the verdict on that claim
//
// The reader chooses what gets checked. Results are kept per claim, so switching back to one
// already checked is instant and costs no request. A verdict describes the claim it sits
// under, never the post: nothing here may call a post true, false or fake.
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
    a { color: #93c5fd; text-decoration: none; word-break: break-word; }
    a:hover { text-decoration: underline; }

    .post {
      background: #131f33; border-radius: 10px; padding: 10px 12px; margin-bottom: 18px;
      font-size: 13px; white-space: pre-wrap; max-height: 130px; overflow: auto;
    }
    .post .who { color: #93c5fd; font-weight: 600; margin-bottom: 4px; }
    .post mark {
      background: rgba(96,165,250,.25); color: #dbeafe;
      border-bottom: 1px solid #60a5fa; border-radius: 2px; padding: 0 1px;
    }

    section { margin-bottom: 20px; }
    section h2 {
      margin: 0 0 4px; font-size: 11px; font-weight: 700;
      text-transform: uppercase; letter-spacing: .08em; color: #94a3b8;
    }
    .hint { font-size: 12px; color: #64748b; margin-bottom: 9px; }

    /* claim picker */
    .claim {
      width: 100%; text-align: left; display: block;
      background: #131f33; border: 1px solid #1e293b; border-radius: 9px;
      padding: 10px 12px; margin-bottom: 8px; cursor: pointer; color: inherit;
      font: inherit; transition: border-color 120ms ease, background 120ms ease;
    }
    .claim:hover { border-color: #3b82f6; background: #16243c; }
    .claim:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
    .claim[aria-expanded="true"] { border-color: #3b82f6; background: #16243c; }
    .claim .ctext { font-size: 13.5px; color: #f1f5f9; }
    .claim .cfoot {
      display: flex; align-items: center; justify-content: space-between;
      gap: 8px; margin-top: 7px;
    }
    .claim .cact { font-size: 11.5px; color: #60a5fa; }
    .claim[aria-expanded="true"] .cact { color: #94a3b8; }

    /* verdict, shown under the claim it belongs to */
    .verdict { margin: -2px 0 10px; padding: 11px 12px; background: #0f1a2e; border: 1px solid #1e293b; border-top: none; border-radius: 0 0 9px 9px; }
    .pill {
      display: inline-block; font-weight: 700; font-size: 11.5px; letter-spacing: .03em;
      text-transform: uppercase; padding: 4px 11px; border-radius: 9999px; white-space: nowrap;
    }
    .pill.green { background: #064e3b; color: #6ee7b7; }
    .pill.amber { background: #78350f; color: #fcd34d; }
    .pill.red   { background: #7f1d1d; color: #fca5a5; }
    .pill.grey  { background: #1e293b; color: #cbd5e1; }
    .verdict .expl { margin-top: 8px; font-size: 13px; }
    .verdict .mc { margin-top: 10px; font-size: 12.5px; color: #cbd5e1; border-left: 2px solid #475569; padding-left: 9px; }
    .verdict .mc b { display: block; font-size: 10.5px; text-transform: uppercase; letter-spacing: .07em; color: #94a3b8; margin-bottom: 2px; font-weight: 700; }

    .cite-list { margin: 9px 0 0; padding: 0; list-style: none; font-size: 12.5px; }
    .cite-list li { margin-bottom: 4px; display: flex; gap: 6px; }
    .cite-n { color: #64748b; flex-shrink: 0; }

    .inline-load { display: flex; align-items: center; gap: 9px; font-size: 12.5px; color: #94a3b8; }
    .dot { width: 14px; height: 14px; border: 2px solid #1e293b; border-top-color: #60a5fa; border-radius: 50%; animation: spin .9s linear infinite; flex-shrink: 0; }
    .inline-err { font-size: 12.5px; color: #fca5a5; }

    /* signals */
    .signal {
      background: #131f33; border: 1px solid #1e293b; border-radius: 9px;
      padding: 9px 11px; margin-bottom: 7px;
    }
    .signal:last-child { margin-bottom: 0; }
    .label { font-weight: 650; font-size: 13px; color: #e2e8f0; }
    .label.other { color: #94a3b8; font-weight: 500; font-style: italic; }
    .caution { font-size: 10.5px; color: #64748b; margin-left: 7px; }
    blockquote {
      margin: 6px 0 0; padding-left: 9px; border-left: 2px solid #3b82f6;
      color: #bfdbfe; font-size: 12.5px; font-style: italic; word-break: break-word;
    }

    .empty { font-size: 12.5px; color: #64748b; font-style: italic; }

    details { border-top: 1px solid #1e293b; padding-top: 12px; }
    summary { cursor: pointer; font-size: 12px; color: #94a3b8; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    summary::before { content: "\\25B8 "; color: #64748b; }
    details[open] summary::before { content: "\\25BE "; }
    .ev { margin-top: 9px; font-size: 12.5px; }
    .ev ul { margin: 0; padding-left: 16px; }
    .ev li { margin-bottom: 8px; }
    .ev .snip { color: #64748b; font-size: 12px; }

    .loading { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 46px 0; text-align: center; }
    .spinner { width: 34px; height: 34px; border: 3px solid #1e293b; border-top-color: #60a5fa; border-radius: 50%; animation: spin .9s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) {
      .spinner, .dot { animation-duration: 2.4s; }
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

      // stage 1 state
      this.data = null;
      this.payload = null;
      this.onCheck = null;
      // claim id -> { state: "loading" | "done" | "error", data, error }
      this.results = new Map();
      this.selected = null;

      this._onKey = (e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          this.close();
        }
      };
    }

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

      // One delegated listener: the claim list is re-rendered on every state change.
      this.body.addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-claim]");
        if (btn) this._toggle(btn.getAttribute("data-claim"));
      });
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
      if (this.lastFocus && document.contains(this.lastFocus)) this.lastFocus.focus();
      this.lastFocus = null;
    }

    // ---------------------------------------------------------------- states

    showLoading(payload, trigger) {
      this.open(trigger);
      this.footer.textContent = "";
      this.body.innerHTML = `
        ${this._postBlock(payload, null)}
        <div class="loading">
          <div class="spinner"></div>
          <div>Reading the post&hellip;</div>
          <div class="muted small">Finding what can be checked, and how the post is written.</div>
        </div>`;
    }

    showError(message, trigger) {
      this.open(trigger);
      this.footer.textContent = "";
      this.body.innerHTML = `
        <div class="error"><strong>Could not read this post.</strong><br>${esc(message)}</div>
        <p class="muted small" style="margin-top:12px">
          Is the backend running? Default is http://127.0.0.1:8000 &mdash; check
          <code>/api/v1/health</code>.
        </p>`;
    }

    /**
     * Stage 1. `onCheck(claim)` is called when the reader picks a claim and must resolve to
     * `{ok:true, data}` or `{ok:false, error}`.
     */
    showClaims(data, payload, onCheck, trigger) {
      this.open(trigger);
      this.data = data;
      this.payload = payload;
      this.onCheck = onCheck;
      this.results = new Map();
      this.selected = null;
      this._render();
      this.body.scrollTop = 0;
    }

    // ---------------------------------------------------------------- claim selection

    async _toggle(claimId) {
      if (this.selected === claimId) {
        this.selected = null; // collapse
        this._render();
        return;
      }
      this.selected = claimId;

      const cached = this.results.get(claimId);
      if (cached && cached.state === "done") {
        this._render(); // already checked: no request
        return;
      }

      const claim = (this.data.claims || []).find((c) => c.id === claimId);
      if (!claim) return;

      this.results.set(claimId, { state: "loading" });
      this._render();

      let res;
      try {
        res = await this.onCheck(claim);
      } catch (err) {
        res = { ok: false, error: String((err && err.message) || err) };
      }

      // The reader may have clicked elsewhere while this was in flight; keep the result
      // either way so coming back to it is instant.
      if (res && res.ok) this.results.set(claimId, { state: "done", data: res.data });
      else this.results.set(claimId, { state: "error", error: (res && res.error) || "Unknown error" });
      this._render();
    }

    _selectedClaim() {
      if (!this.selected) return null;
      return (this.data.claims || []).find((c) => c.id === this.selected) || null;
    }

    // ---------------------------------------------------------------- render

    _render() {
      const d = this.data || {};
      const speaker = d.speaker_context || {};
      const unknownAuthor = norm(speaker.background) === UNKNOWN_AUTHOR;

      this.body.innerHTML = `
        ${this._postBlock(this.payload, this._selectedClaim())}
        ${this._claims(d.claims)}
        ${this._signals(d.rhetorical_signals)}
        ${this._speaker(speaker, unknownAuthor, d.sources)}
        ${this._evidence()}
      `;
      this.footer.innerHTML = this._footer(d);
    }

    // Highlights the selected claim's verbatim span, so the reader sees which words are
    // being checked. Escape first, then wrap - never the other way round.
    _postBlock(payload, claim) {
      if (!payload) return "";
      let text = esc(payload.post_text);
      const quote = claim ? esc(claim.quote || "") : "";
      if (quote && text.includes(quote)) text = text.split(quote).join(`<mark>${quote}</mark>`);
      return `<div class="post">
        <div class="who">${esc(payload.author_name)} <span class="muted">@${esc(payload.author_handle)}</span></div>
        ${text}
      </div>`;
    }

    _claims(claims) {
      const list = claims || [];
      if (!list.length) {
        return `<section>
          <h2>Checkable claims</h2>
          <p class="empty">No checkable factual claim in this post. What follows describes how it is
          written, not whether it is true.</p>
        </section>`;
      }
      const items = list
        .map((c) => {
          const open = this.selected === c.id;
          const r = this.results.get(c.id);
          const action = open ? "Hide" : r && r.state === "done" ? "Show result" : "Check this claim";
          return `<button type="button" class="claim" data-claim="${esc(c.id)}" aria-expanded="${open}">
              <span class="ctext">&ldquo;${esc(c.text)}&rdquo;</span>
              <span class="cfoot"><span class="cact">${action}</span></span>
            </button>
            ${open ? this._verdict(r) : ""}`;
        })
        .join("");
      return `<section>
        <h2>Checkable claims</h2>
        <p class="hint">${list.length === 1 ? "One claim in this post." : `${list.length} claims in this post.`} Pick one to check it against the web.</p>
        ${items}
      </section>`;
    }

    _verdict(r) {
      if (!r) return "";
      if (r.state === "loading") {
        return `<div class="verdict"><div class="inline-load"><div class="dot"></div>
          Searching the web and checking this claim&hellip;</div></div>`;
      }
      if (r.state === "error") {
        return `<div class="verdict"><div class="inline-err">Could not check this claim: ${esc(r.error)}</div></div>`;
      }

      const data = r.data || {};
      const check = data.claim_check || {};
      const v = window.CG_TAXONOMY.verdict(check.verdict);
      const sources = check.sources || [];
      const cites = sources.length
        ? `<ul class="cite-list">${sources
            .map(
              (s, i) => `<li><span class="cite-n">[${i + 1}]</span>
                <a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a></li>`
            )
            .join("")}</ul>`
        : "";
      const mc = data.missing_context && String(data.missing_context).trim()
        ? `<div class="mc"><b>Missing context</b>${esc(data.missing_context)}</div>`
        : "";

      return `<div class="verdict">
        <span class="pill ${v.tone}">${esc(v.label)}</span>
        ${check.explanation ? `<p class="expl">${esc(check.explanation)}</p>` : ""}
        ${cites}
        ${mc}
      </div>`;
    }

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

    // "What we checked against" for the claim currently open.
    _evidence() {
      const r = this.selected && this.results.get(this.selected);
      const list = (r && r.state === "done" && r.data && r.data.evidence) || [];
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
        <summary>What this claim was checked against (${list.length})</summary>
        <div class="ev"><ul>${items}</ul></div>
      </details>`;
    }

    _footer(data) {
      const timing = data.cached ? "cached" : `${data.latency_ms} ms`;
      const meta = [data.provider, data.model, timing].filter(Boolean).map((x) => esc(x)).join(" &middot; ");
      return `${esc(data.disclaimer || "")}<br><span style="opacity:.75">${meta}</span>`;
    }
  }

  window.ContextGuardDrawer = ContextGuardDrawer;
})();
