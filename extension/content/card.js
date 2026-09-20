// The Unfold card: an analysis panel rendered inline inside the tweet, not over it.
//
// Mounted as the last child of the <article>, inside a Shadow DOM so X's stylesheet cannot
// reach in and ours cannot leak out. Colours are read from X's current theme.
//
// Three views:
//   menu   what would you like to check? -> the whole post, or one claim
//   claim  the verdict on one claim (POST /api/v1/analyze-claim)
//   post   every claim checked, plus the post-level signals and speaker
//
// A verdict always describes the claim it sits under. Nothing here labels a post true,
// false or fake.
//
// Exposes window.UnfoldCard. Loaded after taxonomy.js and theme.js.

(() => {
  const STYLE = `
    :host { all: initial; display: block; }
    * { box-sizing: border-box; }

    .card {
      --bg: #ffffff;
      --sunken: #f7f9f9;
      --text: #0f1419;
      --muted: #536471;
      --border: #cfd9de;
      --border-soft: #eff3f4;
      --accent: #1d9bf0;
      --accent-bg: rgba(29,155,240,.1);
      --green: #00743f;  --green-bg: rgba(0,186,124,.14);
      --amber: #8a6100;  --amber-bg: rgba(255,212,0,.18);
      --red:   #c0182a;  --red-bg:   rgba(244,33,46,.12);
      --grey:  #536471;  --grey-bg:  rgba(83,100,113,.12);

      font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: var(--text);
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      margin: 4px 0 12px;
      overflow: hidden;
    }
    .card[data-theme="dark"] {
      --bg: #16202a;
      --sunken: #1c2732;
      --text: #e7e9ea;
      --muted: #8b98a5;
      --border: #38444d;
      --border-soft: #273340;
      --accent: #1d9bf0;
      --accent-bg: rgba(29,155,240,.16);
      --green: #6ee7b7;  --green-bg: rgba(0,186,124,.18);
      --amber: #fcd34d;  --amber-bg: rgba(255,212,0,.16);
      --red:   #fca5a5;  --red-bg:   rgba(244,33,46,.18);
      --grey:  #8b98a5;  --grey-bg:  rgba(139,152,165,.16);
    }

    header {
      display: flex; align-items: center; justify-content: space-between; gap: 10px;
      padding: 11px 14px; border-bottom: 1px solid var(--border-soft);
    }
    .brand { display: flex; align-items: center; gap: 7px; font-weight: 700; font-size: 14px; }
    /* The mark inherits the colour property, so both tones follow X's accent. */
    .uf-icon { display: block; color: var(--accent); flex-shrink: 0; }
    .hmeta { font-size: 13px; color: var(--muted); white-space: nowrap; }

    .view { padding: 13px 14px 4px; }
    .ask { font-size: 14.5px; font-weight: 600; margin: 0 0 11px; }

    /* rows: the full-post button and each claim.
       align-items is flex-start so a claim wrapping to three lines keeps its number in the
       top-left corner rather than drifting to the vertical middle. */
    .row {
      display: flex; align-items: flex-start; gap: 11px; width: 100%; text-align: left;
      background: var(--sunken); border: 1px solid transparent; border-radius: 11px;
      padding: 11px 13px; margin-bottom: 7px; cursor: pointer; color: inherit;
      font: inherit; transition: background 120ms ease, border-color 120ms ease;
    }
    .row:hover { background: var(--accent-bg); border-color: var(--accent); }
    .row:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
    /* The primary row is the same weight and colour as the rest; it earns its outline only
       under the cursor, like every other row. */
    .row .chev { margin-left: auto; color: var(--muted); flex-shrink: 0; font-size: 15px; align-self: center; }
    .row .n {
      font-variant-numeric: tabular-nums; font-size: 12.5px; font-weight: 700;
      color: var(--accent); flex-shrink: 0; min-width: 17px; line-height: 1.5;
    }
    .row .rtext { flex: 1; font-size: 14px; }
    .row .sub { display: block; font-size: 12.5px; color: var(--muted); font-weight: 400; margin-top: 2px; }

    .divider { display: flex; align-items: center; gap: 10px; margin: 13px 0 10px; color: var(--muted); font-size: 12.5px; }
    .divider::before, .divider::after { content: ""; flex: 1; height: 1px; background: var(--border-soft); }

    /* Section titles sit back from the prose: lighter weight and wider tracking, so they
       read as labels rather than competing with the sentence underneath. */
    h3 {
      margin: 0 0 6px; font-size: 11px; font-weight: 500; letter-spacing: .09em;
      text-transform: uppercase; color: var(--muted); opacity: .85;
    }
    .block { padding: 13px 0; border-top: 1px solid var(--border-soft); }
    .block:first-child { border-top: none; padding-top: 0; }
    p { margin: 0; font-size: 14px; }
    .lead { font-size: 14.5px; }

    .pill {
      display: inline-block; font-weight: 700; font-size: 11.5px; letter-spacing: .02em;
      text-transform: uppercase; padding: 3px 10px; border-radius: 9999px;
    }
    .pill.green { color: var(--green); background: var(--green-bg); }
    .pill.amber { color: var(--amber); background: var(--amber-bg); }
    .pill.red   { color: var(--red);   background: var(--red-bg); }
    .pill.grey  { color: var(--grey);  background: var(--grey-bg); }

    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .signals { list-style: none; margin: 0; padding: 0; }
    .signals li { margin: 0 0 10px; }
    .signals li:last-child { margin-bottom: 0; }
    .signals blockquote { margin-top: 5px; }
    .no-quote { font-size: 12.5px; color: var(--muted); margin-left: 8px; }
    /* Badges carry the accent rather than body black, and sit lighter than the prose:
       300 where the font has a Light cut, otherwise the browser rounds it to normal. */
    .chip {
      font-size: 12.5px; padding: 7px 12px; border-radius: 9999px;
      background: var(--accent-bg); color: var(--accent); font-weight: 300;
      letter-spacing: .01em; line-height: 1.2;
    }
    .chip.other { color: var(--muted); font-style: italic; }
    /* Dog Whistle, Scapegoating, Dehumanization. UF_TAXONOMY.isHighRisk has always been
       exported; until now nothing called it and these rendered as ordinary chips. */
    .chip.risk { background: var(--amber-bg); color: var(--amber); }
    .chip .q { color: var(--muted); }

    /* Hover definition. A name like "Dog Whistle" is jargon, so the chip carries its own
       explanation: dotted underline to say there is something to read, opened by the cursor
       and by keyboard focus alike. Solid accent on white, the same blue the badge already
       uses, and absolute so opening it never moves the rows underneath. */
    .chip-wrap { position: relative; display: inline-block; }
    .chip-wrap .chip {
      cursor: help;
      text-decoration: underline dotted currentColor;
      text-underline-offset: 3px;
    }
    .tip {
      position: absolute; left: 50%; bottom: calc(100% + 7px); z-index: 3;
      width: max-content; max-width: 240px;
      padding: 7px 10px; border-radius: 9px;
      background: var(--accent); color: #fff;
      box-shadow: 0 2px 10px rgba(0,0,0,.18);
      font-size: 12.5px; line-height: 1.35; font-weight: 400; letter-spacing: 0;
      opacity: 0; visibility: hidden; pointer-events: none;
      transition: opacity 120ms ease;
    }
    /* Opens up and to the right of the badge, anchored at its middle, so a 240px box still
       clears the card's right edge even after the widest label in the taxonomy. */
    .tip::after {
      content: ""; position: absolute; top: 100%; left: 13px;
      border: 5px solid transparent; border-bottom: 0; border-top-color: var(--accent);
    }
    .chip-wrap:hover .tip, .chip:focus-visible + .tip { opacity: 1; visibility: visible; }
    @media (prefers-reduced-motion: reduce) { .tip { transition: none; } }

    blockquote {
      margin: 8px 0 0; padding-left: 10px; border-left: 3px solid var(--accent);
      font-size: 13.5px; color: var(--muted); word-break: break-word;
    }

    ol.cites { margin: 9px 0 0; padding: 0; list-style: none; font-size: 13px; }
    ol.cites li { margin-bottom: 4px; display: flex; gap: 7px; }
    ol.cites .n { color: var(--muted); flex-shrink: 0; font-variant-numeric: tabular-nums; }
    a { color: var(--accent); text-decoration: none; word-break: break-word; }
    a:hover { text-decoration: underline; }

    /* "What is missing" is body copy, not an aside: same size and colour as the rest. */
    .missing { margin-top: 13px; }
    .missing h3 { margin-bottom: 5px; }
    .empty { font-size: 13.5px; color: var(--muted); }

    /* Collapsed source list. The twisty is the same glyph the claim rows use, rotated when
       open, so one chevron shape means "there is more this way" everywhere in the card. */
    details { margin-top: 13px; }
    summary {
      display: flex; align-items: center; gap: 7px; cursor: pointer; list-style: none;
      font-size: 13px; color: var(--muted); padding: 2px 0; transition: color 120ms ease;
    }
    summary:hover { color: var(--accent); }
    summary::-webkit-details-marker { display: none; }
    summary::marker { content: ""; }
    summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
    .tw::before {
      content: "\\203A"; display: inline-block; font-size: 15px; line-height: 1;
      transition: transform 140ms ease; transform-origin: 45% 50%;
    }
    details[open] .tw::before { transform: rotate(90deg); }
    @media (prefers-reduced-motion: reduce) { .tw::before { transition: none; } }

    /* At the foot of the full post the list is the whole block, so it opens flush with the
       section above rather than carrying the gap it needs under a claim's explanation. */
    .block.allsrc details { margin-top: 0; }

    ol.srclist { margin: 9px 0 0; padding: 0; list-style: none; font-size: 13px; }
    ol.srclist li { display: flex; gap: 8px; margin-bottom: 9px; }
    ol.srclist li:last-child { margin-bottom: 0; }
    ol.srclist .n {
      color: var(--muted); flex-shrink: 0; font-variant-numeric: tabular-nums;
      min-width: 13px; text-align: right;
    }
    ol.srclist .src { display: block; }
    ol.srclist .snip { display: block; color: var(--muted); font-size: 12.5px; margin-top: 2px; }
    ol.srclist .cited {
      display: inline-block; margin-left: 6px; font-size: 10.5px; font-weight: 500;
      letter-spacing: .04em; text-transform: uppercase; color: var(--muted);
      border: 1px solid var(--border); border-radius: 4px; padding: 0 4px; vertical-align: 1px;
    }

    /* verdict marker on a claim row that has already been checked */
    .dot {
      display: inline-block; width: 7px; height: 7px; border-radius: 50%;
      margin-right: 6px; vertical-align: middle;
    }
    .dot.green { background: var(--green); }
    .dot.amber { background: var(--amber); }
    .dot.red   { background: var(--red); }
    .dot.grey  { background: var(--grey); }

    footer {
      display: flex; align-items: center; justify-content: space-between; gap: 10px;
      padding: 10px 14px; border-top: 1px solid var(--border-soft); background: var(--sunken);
    }
    /* Navigation, not a call to action: grey until the cursor is on it, never underlined.
       The chevrons are the same glyphs the claim rows use, so forward and back read alike. */
    footer button {
      display: inline-flex; align-items: center; gap: 6px;
      background: none; border: none; padding: 4px 2px; cursor: pointer; color: var(--muted);
      font: 500 13.5px/1.2 inherit; border-radius: 6px;
      transition: color 120ms ease;
    }
    footer button:hover { color: var(--accent); }
    footer button:hover .chev { color: var(--accent); }
    footer button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    footer .chev { color: var(--muted); font-size: 15px; line-height: 1; transition: color 120ms ease; }
    footer .spacer { flex: 1; }
    .disclaimer { padding: 9px 14px 11px; font-size: 11.5px; line-height: 1.4; color: var(--muted); }

    .loading { display: flex; align-items: center; gap: 10px; padding: 18px 0 22px; font-size: 14px; color: var(--muted); }
    .spinner {
      width: 17px; height: 17px; border: 2px solid var(--border);
      border-top-color: var(--accent); border-radius: 50%; animation: spin .9s linear infinite; flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 2.4s; } }
    .error { font-size: 13.5px; color: var(--red); padding: 4px 0 14px; }
  `;

  // Everything that reaches innerHTML goes through this. The post is written by a stranger
  // and the model output is influenced by it, so neither is ever trusted.
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  // Sources are matched on the URL with any trailing slashes off: the same page reaches us
  // from a search and from a citation list written two different ways.
  const srcKey = (u) => String(u ?? "").replace(/\/+$/, "");

  // Every view that is not the menu returns to it the same way.
  const BACK_BUTTON =
    '<button type="button" data-act="menu"><span class="chev">&lsaquo;</span>Go back</button>';

  const UNKNOWN_AUTHOR = "unknown author";
  const norm = (s) => String(s ?? "").trim().replace(/\.$/, "").toLowerCase();
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  // "one", "two"... reads better than a digit mid-sentence for the small numbers we ever hit.
  const WORDS = ["no", "one", "two", "three", "four", "five", "six"];
  const count = (n) => WORDS[n] || String(n);

  class UnfoldCard {
    /**
     * @param {HTMLElement} article  the tweet this card belongs to
     * @param {object} payload       scraped post: author_name, author_handle, post_text
     * @param {object} api           { claims(), checkClaim(claim) } -> {ok, data} | {ok:false, error}
     * @param {HTMLElement} [anchor] element to insert the card after, normally the action bar
     */
    constructor(article, payload, api, anchor) {
      this.article = article;
      this.payload = payload;
      this.api = api;
      this.anchor = anchor || null;

      this.host = null;
      this.root = null;
      this.cardEl = null;

      this.view = "loading"; // loading | menu | claim | post | error
      this.error = "";
      this.claimsData = null;
      this.results = new Map(); // claim id -> { state, data, error }
      this.currentId = null;
      this.postState = "idle"; // idle | loading | done
      this.stopTheme = null;
    }

    // ---------------------------------------------------------------- mount

    mount() {
      if (this.host) return;
      this.host = document.createElement("div");
      this.host.className = "uf-card-host";
      // X wraps the whole tweet in a click handler that navigates to the status page.
      // Everything inside the card must stay inside the card.
      for (const type of ["click", "mousedown", "mouseup", "keydown", "keyup"]) {
        this.host.addEventListener(type, (e) => e.stopPropagation());
      }

      // The <article> is a flex ROW: avatar column, then content column. Appending to it
      // would drop the card in as a third column beside the tweet. It belongs after the
      // action bar, inside the content column, where it reads as part of the post.
      if (this.anchor && this.anchor.parentNode) {
        this.anchor.parentNode.insertBefore(this.host, this.anchor.nextSibling);
      } else {
        this.article.appendChild(this.host);
      }

      this.root = this.host.attachShadow({ mode: "open" });
      this.root.innerHTML = `<style>${STYLE}</style><div class="card"></div>`;
      this.cardEl = this.root.querySelector(".card");
      this._applyPalette(window.UF_THEME.current(), window.UF_THEME.accent());
      this.stopTheme = window.UF_THEME.onChange((mode, accent) => this._applyPalette(mode, accent));

      this.cardEl.addEventListener("click", (ev) => {
        const el = ev.target.closest("[data-act]");
        if (el) this._act(el.getAttribute("data-act"), el.getAttribute("data-id"));
      });
    }

    // X's accent is a user setting with six options, so it is read from the page rather than
    // hard-coded. --accent drives the icon, the row highlights and every link in the card.
    _applyPalette(mode, accent) {
      if (!this.cardEl) return;
      this.cardEl.setAttribute("data-theme", mode);
      this.cardEl.style.setProperty("--accent", accent);
      // The soft wash behind a selected row: the same colour, mostly transparent.
      const rgb = String(accent).match(/\d+/g);
      if (rgb && rgb.length >= 3) {
        this.cardEl.style.setProperty("--accent-bg", `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${mode === "dark" ? 0.18 : 0.1})`);
      }
    }

    get mounted() {
      return Boolean(this.host && this.host.isConnected);
    }

    destroy() {
      if (this.stopTheme) this.stopTheme();
      if (this.host && this.host.parentNode) this.host.parentNode.removeChild(this.host);
      this.host = null;
      this.stopTheme = null;
    }

    // ---------------------------------------------------------------- flow

    async start() {
      this.mount();
      this.view = "loading";
      this._render();

      const res = await this.api.claims();
      if (res && res.ok) {
        this.claimsData = res.data;
        this.view = "menu";
      } else {
        this.error = (res && res.error) || "Unknown error";
        this.view = "error";
      }
      this._render();
    }

    // Returns the pending work so callers can await a view transition; the click handler
    // ignores it.
    _act(action, id) {
      if (action === "claim") return this._openClaim(id);
      if (action === "post") return this._openPost();
      if (action === "menu") {
        this.view = "menu";
        this.currentId = null;
        this._render();
      } else if (action === "close") {
        this.destroy();
      }
      return Promise.resolve();
    }

    async _openClaim(id) {
      this.view = "claim";
      this.currentId = id;
      this._render();

      const existing = this.results.get(id);
      if (existing && existing.state === "done") return; // already checked: no request

      const claim = this._claims().find((c) => c.id === id);
      if (!claim) return;

      this.results.set(id, { state: "loading" });
      this._render();
      await this._check(claim);
      this._render();
    }

    async _check(claim) {
      let res;
      try {
        res = await this.api.checkClaim(claim);
      } catch (err) {
        res = { ok: false, error: String((err && err.message) || err) };
      }
      if (res && res.ok) this.results.set(claim.id, { state: "done", data: res.data });
      else this.results.set(claim.id, { state: "error", error: (res && res.error) || "Unknown error" });
    }

    // The whole post means every claim checked. They are independent, so they go out together.
    async _openPost() {
      this.view = "post";
      this.currentId = null;
      const pending = this._claims().filter((c) => {
        const r = this.results.get(c.id);
        return !r || r.state === "error";
      });
      if (!pending.length) {
        this.postState = "done";
        this._render();
        return;
      }
      this.postState = "loading";
      this._render();
      await Promise.all(pending.map((c) => this._check(c)));
      this.postState = "done";
      this._render();
    }

    _claims() {
      return (this.claimsData && this.claimsData.claims) || [];
    }

    // ---------------------------------------------------------------- render

    _render() {
      if (!this.cardEl) return;
      const head = this._header();
      let view = "";
      let foot = "";

      if (this.view === "loading") {
        view = `<div class="view"><div class="loading"><div class="spinner"></div>
          Reading the post and finding what can be checked&hellip;</div></div>`;
      } else if (this.view === "error") {
        view = `<div class="view"><div class="error">Could not read this post: ${esc(this.error)}</div>
          <p class="empty" style="padding-bottom:14px">Is the backend running on http://127.0.0.1:8000?</p></div>`;
      } else if (this.view === "menu") {
        view = this._menu();
      } else if (this.view === "claim") {
        view = this._claimView();
        foot = this._claimFooter();
      } else if (this.view === "post") {
        view = this._postView();
        foot = `${BACK_BUTTON}<span class="spacer"></span>`;
      }

      const disclaimer =
        this.view === "menu" || this.view === "loading" || this.view === "error"
          ? ""
          : `<div class="disclaimer">${esc((this.claimsData && this.claimsData.disclaimer) || "")}</div>`;

      this.cardEl.innerHTML =
        head + view + disclaimer + (foot ? `<footer>${foot}</footer>` : "");
    }

    _header() {
      let meta = "";
      if (this.view === "menu" && this.claimsData) {
        const n = this._claims().length;
        meta = n ? `${plural(n, "claim", "claims")} found` : "No checkable claims";
      } else if (this.view === "claim" && this.currentId) {
        const i = this._claims().findIndex((c) => c.id === this.currentId);
        meta = `Claim ${i + 1} of ${this._claims().length}`;
      }
      // The full-post view carries no count: the sources live in each claim's own list, so a
      // total in the corner counted things the reader could not see from here.
      return `<header>
        <span class="brand">${window.UF_ICON.svg(19)}Unfold</span>
        <span class="hmeta">${esc(meta)}</span>
      </header>`;
    }

    // ---- menu -------------------------------------------------------

    _menu() {
      const claims = this._claims();
      // This menu is the only claim list now, so a claim already checked carries its verdict
      // here rather than in a second list inside the full-post view.
      const rows = claims
        .map((c, i) => {
          const r = this.results.get(c.id);
          let status = "";
          if (r && r.state === "done") {
            const v = window.UF_TAXONOMY.verdict(r.data.claim_check && r.data.claim_check.verdict);
            status = `<span class="sub"><span class="dot ${v.tone}"></span>${esc(v.label)}</span>`;
          } else if (r && r.state === "error") {
            status = `<span class="sub"><span class="dot grey"></span>Could not check</span>`;
          }
          return `<button type="button" class="row" data-act="claim" data-id="${esc(c.id)}">
            <span class="n">${String(i + 1).padStart(2, "0")}</span>
            <span class="rtext">&ldquo;${esc(c.text)}&rdquo;${status}</span>
            <span class="chev">&rsaquo;</span>
          </button>`;
        })
        .join("");

      return `<div class="view">
        <p class="ask">What would you like to check?</p>
        <button type="button" class="row primary" data-act="post">
          <span class="rtext">Analyze the full post</span>
          <span class="chev">&rsaquo;</span>
        </button>
        ${
          claims.length
            ? `<div class="divider">or choose a claim</div>${rows}`
            : `<p class="empty" style="margin-top:12px">No checkable factual claim in this post.
               The full analysis still shows how it is written and who is speaking.</p>`
        }
        <div style="height:9px"></div>
      </div>`;
    }

    // ---- one claim --------------------------------------------------

    _claimView() {
      const claim = this._claims().find((c) => c.id === this.currentId);
      if (!claim) return `<div class="view"><p class="empty">Claim not found.</p></div>`;
      const r = this.results.get(this.currentId);

      let result = "";
      if (!r || r.state === "loading") {
        result = `<div class="loading"><div class="spinner"></div>Searching the web and checking this claim&hellip;</div>`;
      } else if (r.state === "error") {
        result = `<div class="error">Could not check this claim: ${esc(r.error)}</div>`;
      } else {
        result = this._verdictBlock(r.data);
      }

      // claim.quote is not rendered. It is the post's own wording of the same sentence, so
      // under the claim it read as a stutter; the words the post actually used are still on
      // screen in the post itself, right above the card.
      return `<div class="view">
        <div class="block">
          <h3>Claim</h3>
          <p class="lead">&ldquo;${esc(claim.text)}&rdquo;</p>
        </div>
        <div class="block">${result}</div>
      </div>`;
    }

    _verdictBlock(data) {
      const check = data.claim_check || {};
      const v = window.UF_TAXONOMY.verdict(check.verdict);
      const missing =
        data.missing_context && String(data.missing_context).trim()
          ? `<div class="missing"><h3>What is missing</h3><p>${esc(data.missing_context)}</p></div>`
          : "";

      return `<span class="pill ${v.tone}">${esc(v.label)}</span>
        ${check.explanation ? `<p style="margin-top:9px">${esc(check.explanation)}</p>` : ""}
        ${this._sources(data)}
        ${missing}`;
    }

    /**
     * One collapsed list rather than two open ones: the five links the verdict rests on and
     * the five pages we searched were the same five, printed twice.
     *
     * Everything searched is listed, and the entries the verdict actually leans on are
     * marked. That distinction is the honest part - a page we read and set aside is not the
     * same as a page we relied on - so it survives the merge instead of being flattened away.
     */
    _sources(data) {
      const evidence = data.evidence || [];
      const cited = data.claim_check && data.claim_check.sources ? data.claim_check.sources : [];
      // cited is guaranteed a subset of evidence by the server, but fall back rather than
      // show nothing if that ever stops holding.
      const items = evidence.length ? evidence : cited;
      return this._sourceList(items, new Set(cited.map((s) => srcKey(s.url))));
    }

    /** The one list markup, shared by a single claim and by the full post. */
    _sourceList(items, citedUrls) {
      if (!items.length) return "";
      const rows = items
        .map((e, i) => {
          const isCited = citedUrls.has(srcKey(e.url));
          return `<li>
            <span class="n">${i + 1}</span>
            <span class="src">
              <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)}</a>
              ${isCited ? `<span class="cited">cited</span>` : ""}
              ${e.snippet ? `<span class="snip">${esc(e.snippet)}</span>` : ""}
            </span>
          </li>`;
        })
        .join("");

      return `<details class="sources">
        <summary><span class="tw"></span>List of sources (${items.length})</summary>
        <ol class="srclist">${rows}</ol>
      </details>`;
    }

    /**
     * Every page the whole analysis touched, in one list at the foot of the full-post view:
     * each claim's searches, the pages its verdict cites, and the post-level reading the
     * speaker block links to - which on a post with no checkable claim is all there is.
     *
     * Deduplicated on the URL, because two claims searching the same topic come back with
     * the same pages, and a page carries the "cited" tag if any claim's verdict leaned on it.
     */
    _allSourcesBlock() {
      const byUrl = new Map();
      const citedUrls = new Set();
      const add = (e) => {
        if (!e || !e.url) return;
        const k = srcKey(e.url);
        const prev = byUrl.get(k);
        // Keep the richer entry: the same page arrives with a snippet from a search and
        // without one from a citation list.
        if (!prev || (!prev.snippet && e.snippet)) byUrl.set(k, e);
      };

      for (const r of this.results.values()) {
        if (r.state !== "done") continue;
        for (const e of r.data.evidence || []) add(e);
        for (const c of (r.data.claim_check && r.data.claim_check.sources) || []) {
          add(c);
          citedUrls.add(srcKey(c.url));
        }
      }
      for (const s of (this.claimsData && this.claimsData.sources) || []) add(s);

      const list = this._sourceList([...byUrl.values()], citedUrls);
      return list ? `<div class="block allsrc">${list}</div>` : "";
    }

    _claimFooter() {
      const claims = this._claims();
      const i = claims.findIndex((c) => c.id === this.currentId);
      const next = claims[i + 1];
      return `${BACK_BUTTON}
        <span class="spacer"></span>
        ${
          next
            ? `<button type="button" data-act="claim" data-id="${esc(next.id)}">Open claim ${i + 2}<span class="chev">&rsaquo;</span></button>`
            : `<button type="button" data-act="post">Full post<span class="chev">&rsaquo;</span></button>`
        }`;
    }

    // ---- full post --------------------------------------------------

    _postView() {
      const d = this.claimsData || {};
      const speaker = d.speaker_context || {};
      const claims = this._claims();

      if (this.postState === "loading") {
        return `<div class="view"><div class="loading"><div class="spinner"></div>
          Checking ${plural(claims.length, "claim", "claims")} against the web&hellip;</div></div>`;
      }

      // No per-claim list here: the menu behind "All claims" already is that list, and
      // repeating it made the same rows appear twice one tap apart.
      return `<div class="view">
        ${this._overview(claims)}
        ${this._whatIsMissing()}
        ${this._signalsBlock(d.rhetorical_signals)}
        ${this._speakerBlock(speaker, d.sources)}
        ${this._allSourcesBlock()}
      </div>`;
    }

    // Derived from the verdicts actually returned, never invented: the client has no basis
    // for a claim about what the post is "really saying".
    _overview(claims) {
      if (!claims.length) {
        return `<div class="block">
          <h3>Post overview</h3>
          <p class="lead">There is no factual claim here to check. What follows describes how the
          post is written and who is speaking, not whether it is true.</p>
        </div>`;
      }
      const tally = { supported: 0, partially_supported: 0, unsupported: 0, unverifiable: 0 };
      let noAnswer = 0;
      for (const c of claims) {
        const r = this.results.get(c.id);
        if (!r || r.state !== "done") { noAnswer++; continue; }
        const key = r.data.claim_check && r.data.claim_check.verdict;
        // Anything outside the four verdicts - a request that failed, or no_factual_claim on a
        // row we offered as a claim - is a claim the reader got no answer on. Counting it here
        // rather than nowhere keeps the buckets adding up to the number of claims.
        if (key in tally) tally[key] += 1;
        else noAnswer += 1;
      }
      const total = claims.length;

      // Nothing to qualify: say so in one clause, with no arithmetic in front of it.
      if (tally.supported === total) {
        const line =
          total === 1
            ? "The claim in this post is supported by the sources found."
            : total === 2
              ? "Both claims in this post are supported by the sources found."
              : `All ${count(total)} claims in this post are supported by the sources found.`;
        return `<div class="block">
          <h3>Post overview</h3>
          <p class="lead">${line}</p>
        </div>`;
      }

      // Otherwise name only what is not settled, in plain words. The supported ones are the
      // remainder and spelling them out is what made this sentence read like a tally sheet.
      // "unverifiable" and a failed check both leave the reader without an answer, so they are
      // one phrase, not two shades of failure.
      const buckets = [
        [tally.unsupported, "is not supported by the sources found", "are not supported by the sources found"],
        [tally.partially_supported, "is only partly supported", "are only partly supported"],
        [tally.unverifiable + noAnswer, "could not be checked", "could not be checked"],
      ];
      const parts = buckets
        .filter(([n]) => n > 0)
        .map(([n, one, many]) => `${count(n)} ${n === 1 ? one : many}`);

      const sentence = !parts.length
        ? `${plural(total, "claim", "claims")} in this post.`
        : total === 1
          ? `The claim in this post ${buckets.find(([n]) => n > 0)[1]}.`
          : `Of ${count(total)} claims in this post, ${joinList(parts)}.`;

      return `<div class="block">
        <h3>Post overview</h3>
        <p class="lead">${esc(sentence)}</p>
      </div>`;
    }

    _whatIsMissing() {
      const notes = [];
      for (const c of this._claims()) {
        const r = this.results.get(c.id);
        if (!r || r.state !== "done") continue;
        const text = String(r.data.missing_context || "").trim();
        if (text && !notes.includes(text)) notes.push(text);
      }
      if (!notes.length) return "";
      return `<div class="block">
        <h3>What is missing</h3>
        ${notes.map((n) => `<p style="margin-bottom:6px">${esc(n)}</p>`).join("")}
      </div>`;
    }

    _signalsBlock(signals) {
      const list = signals || [];
      if (!list.length) return "";
      // One row per signal. A chip on its own is an accusation; the words that triggered it are
      // what lets the reader disagree, so every signal shows its own quote, not just the first.
      return `<div class="block">
        <h3>Post signals</h3>
        <ul class="signals">${list
          .map((s, i) => {
            const other = window.UF_TAXONOMY.isUncategorised(s.name);
            const risk = window.UF_TAXONOMY.isHighRisk(s.name);
            const cls = ["chip", other ? "other" : "", risk ? "risk" : ""].filter(Boolean).join(" ");
            // A label the model invented has no definition, so that chip gets no tooltip and
            // no underline rather than an empty box. Ids are Shadow DOM-local.
            const why = window.UF_TAXONOMY.meaning(s.name);
            const tipId = `tip-${i}`;
            const chip = why
              ? `<span class="chip-wrap"><span class="${cls}" tabindex="0" aria-describedby="${tipId}">${esc(
                  s.name
                )}</span><span class="tip" id="${tipId}" role="tooltip">${esc(why)}</span></span>`
              : `<span class="${cls}">${esc(s.name)}</span>`;
            return `<li>
              ${chip}
              ${s.evidence ? `<blockquote>${esc(s.evidence)}</blockquote>` : `<span class="no-quote">no quote returned</span>`}
            </li>`;
          })
          .join("")}</ul>
      </div>`;
    }

    _speakerBlock(speaker, sources) {
      const unknown = norm(speaker.background) === UNKNOWN_AUTHOR;
      const nameLine = [speaker.name, speaker.role].filter((s) => s && String(s).trim()).map(esc).join(" &middot; ");
      if (unknown) {
        return `<div class="block">
          <h3>About the speaker</h3>
          <p>${nameLine}</p>
          <p class="empty" style="margin-top:4px">No public background found, so nothing here is
          verified about who is speaking.</p>
        </div>`;
      }
      const list = sources || [];
      return `<div class="block">
        <h3>About the speaker</h3>
        <p>${esc(speaker.background)}</p>
        ${
          list.length
            ? `<ol class="cites">${list
                .map(
                  (s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a></li>`
                )
                .join("")}</ol>`
            : ""
        }
      </div>`;
    }

  }

  function joinList(parts) {
    if (parts.length === 1) return parts[0];
    return parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
  }

  window.UnfoldCard = UnfoldCard;
})();
