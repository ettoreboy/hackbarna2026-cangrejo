// Runs inside the x.com page. Finds tweets, injects the Unfold button, scrapes the post,
// and mounts the analysis card inline in the tweet.
//
// A content script cannot call the backend directly - X's Content-Security-Policy blocks it -
// so every request goes through the service worker. That is why background.js exists.
//
// Every X-specific selector lives in SELECTORS. When X renames a data-testid, this map is the
// only place that needs fixing.

(() => {
  if (window.__unfoldLoaded) return;
  window.__unfoldLoaded = true;

  // Firefox exposes the promise-flavoured `browser`; Chrome only has `chrome`. One name for both.
  const api = globalThis.browser ?? globalThis.chrome;

  const SELECTORS = {
    tweet: 'article[data-testid="tweet"]',
    text: '[data-testid="tweetText"]',
    userName: '[data-testid="User-Name"]',
    replyButton: '[data-testid="reply"]',
    actionBar: '[role="group"]',
    statusLink: 'a[href*="/status/"]',
    video: 'video, [data-testid="videoPlayer"]',
  };

  const MARK = "data-uf-injected";

  // Flip to true once POST /api/v1/analyze-media exists on the backend (owner: Ettore).
  // Until then video posts fall back to their caption text.
  const MEDIA_ENABLED = false;

  // article -> the card mounted in it, so the button toggles rather than stacking cards.
  const cards = new WeakMap();

  // ------------------------------------------------------------------ scraping

  function extractPost(article) {
    const textEl = article.querySelector(SELECTORS.text);
    const post_text = textEl ? textEl.innerText.trim() : "";

    // The User-Name block holds the display name and "@handle" as separate spans.
    const nameBlock = article.querySelector(SELECTORS.userName);
    let author_name = "";
    let author_handle = "";
    if (nameBlock) {
      const spans = Array.from(nameBlock.querySelectorAll("span"))
        .map((s) => s.textContent.trim())
        .filter(Boolean);
      author_handle = (spans.find((t) => t.startsWith("@")) || "").replace(/^@/, "");
      author_name = spans.find((t) => !t.startsWith("@") && t !== "·") || author_handle;
    }

    let post_url;
    const link = article.querySelector(SELECTORS.statusLink);
    if (link) {
      try {
        post_url = new URL(link.getAttribute("href"), location.origin).toString();
      } catch {
        post_url = undefined;
      }
    }

    return {
      author_handle,
      author_name,
      post_text,
      platform: "x",
      post_url,
      has_video: Boolean(article.querySelector(SELECTORS.video)),
    };
  }

  // X nests several [role="group"] elements; the action bar is the one holding the reply
  // button. Falling back to the first group keeps us working if that testid moves.
  function findActionBar(article) {
    const reply = article.querySelector(SELECTORS.replyButton);
    const viaReply = reply && reply.closest(SELECTORS.actionBar);
    return viaReply || article.querySelector(SELECTORS.actionBar);
  }

  // ------------------------------------------------------------------ requests

  function postBody(payload) {
    return {
      author_handle: payload.author_handle,
      author_name: payload.author_name,
      post_text: payload.post_text,
      platform: "x",
      post_url: payload.post_url,
    };
  }

  function apiFor(payload) {
    return {
      // Stage 1: what is checkable in this post. Nothing is checked yet.
      claims() {
        if (MEDIA_ENABLED && payload.has_video) {
          return api.runtime.sendMessage({
            type: "ANALYZE_MEDIA",
            payload: {
              post_url: payload.post_url,
              author_handle: payload.author_handle,
              author_name: payload.author_name,
              platform: "x",
            },
          });
        }
        return api.runtime.sendMessage({ type: "CLAIMS", payload: postBody(payload) });
      },
      // Stage 2: check the one claim the reader picked.
      checkClaim(claim) {
        return api.runtime.sendMessage({
          type: "ANALYZE_CLAIM",
          payload: { ...postBody(payload), claim },
        });
      },
    };
  }

  // ------------------------------------------------------------------ injection

  function injectButton(article) {
    if (article.hasAttribute(MARK)) return;
    const actions = findActionBar(article);
    if (!actions) return;
    article.setAttribute(MARK, "1");

    const btn = document.createElement("button");
    btn.className = "uf-btn";
    btn.type = "button";
    btn.title = "Unfold what this post claims";
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML = '<span class="uf-mark">U</span><span>Unfold</span>';

    btn.addEventListener("click", async (ev) => {
      // X wraps tweets in a click handler that navigates to the post. Stop that.
      ev.preventDefault();
      ev.stopPropagation();

      // Open cards toggle shut; a card X recycled away is rebuilt.
      const existing = cards.get(article);
      if (existing && existing.mounted) {
        existing.destroy();
        cards.delete(article);
        btn.dataset.state = "";
        btn.setAttribute("aria-expanded", "false");
        return;
      }

      const payload = extractPost(article);
      if (!payload.post_text || !payload.author_handle) {
        return; // nothing to read; leave the timeline untouched
      }

      // Anchor the card after the action bar so it lands in the tweet's content column.
      // Resolved again here: React may have replaced the bar since the button went in.
      const anchor = findActionBar(article) || actions;
      const card = new window.UnfoldCard(article, payload, apiFor(payload), anchor);
      cards.set(article, card);
      btn.dataset.state = "open";
      btn.setAttribute("aria-expanded", "true");
      await card.start();
    });

    actions.appendChild(btn);
  }

  function scan(root) {
    (root || document).querySelectorAll(SELECTORS.tweet).forEach(injectButton);
  }

  // X is a single-page app: tweets stream in as you scroll and there is no page-load event to
  // hook. Watch the DOM instead.
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        if (node.matches && node.matches(SELECTORS.tweet)) injectButton(node);
        else scan(node);
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
  scan();
})();
