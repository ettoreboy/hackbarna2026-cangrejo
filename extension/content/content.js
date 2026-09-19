// Runs inside the x.com page. Finds tweets, injects the button, scrapes the post,
// and asks the service worker to call the backend (a content script cannot call it
// directly - X's Content-Security-Policy blocks that, which is why background.js exists).
//
// Every X-specific selector lives in SELECTORS. When X renames a data-testid, this map
// is the only place that needs fixing.

(() => {
  if (window.__contextGuardLoaded) return;
  window.__contextGuardLoaded = true;

  const SELECTORS = {
    tweet: 'article[data-testid="tweet"]',
    text: '[data-testid="tweetText"]',
    userName: '[data-testid="User-Name"]',
    replyButton: '[data-testid="reply"]',
    actionBar: '[role="group"]',
    statusLink: 'a[href*="/status/"]',
    video: 'video, [data-testid="videoPlayer"]',
  };

  const MARK = "data-cg-injected";

  // Flip to true once POST /api/v1/analyze-media exists on the backend (owner: Ettore).
  // Until then video posts fall back to their caption text.
  const MEDIA_ENABLED = false;

  const drawer = new window.ContextGuardDrawer();

  // article -> last successful { data, payload }, so re-opening a post we already
  // analysed is instant and costs no tokens.
  const resultCache = new WeakMap();

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

  // X nests several [role="group"] elements; the action bar is the one holding the
  // reply button. Falling back to the first group keeps us working if that testid moves.
  function findActionBar(article) {
    const reply = article.querySelector(SELECTORS.replyButton);
    const viaReply = reply && reply.closest(SELECTORS.actionBar);
    return viaReply || article.querySelector(SELECTORS.actionBar);
  }

  // ------------------------------------------------------------------ request

  async function requestAnalysis(payload) {
    const useMedia = MEDIA_ENABLED && payload.has_video;
    const type = useMedia ? "ANALYZE_MEDIA" : "ANALYZE";

    const body = useMedia
      ? {
          post_url: payload.post_url,
          author_handle: payload.author_handle,
          author_name: payload.author_name,
          platform: "x",
        }
      : {
          author_handle: payload.author_handle,
          author_name: payload.author_name,
          post_text: payload.post_text,
          platform: "x",
          post_url: payload.post_url,
        };

    return chrome.runtime.sendMessage({ type, payload: body });
  }

  // ------------------------------------------------------------------ injection

  function injectButton(article) {
    if (article.hasAttribute(MARK)) return;
    const actions = findActionBar(article);
    if (!actions) return;
    article.setAttribute(MARK, "1");

    const btn = document.createElement("button");
    btn.className = "cg-btn";
    btn.type = "button";
    btn.title = "Unpack how this post is built";
    btn.innerHTML = '\u{1F6E1}️ <span>Context</span>';

    btn.addEventListener("click", async (ev) => {
      // X wraps tweets in a click handler that navigates to the post. Stop that.
      ev.preventDefault();
      ev.stopPropagation();

      if (btn.dataset.state === "loading") return;

      const payload = extractPost(article);

      // Re-opening something we already analysed: no network call.
      const cached = resultCache.get(article);
      if (cached) {
        drawer.showResult(cached.data, cached.payload, btn);
        return;
      }

      if (!payload.post_text || !payload.author_handle) {
        const why = payload.has_video
          ? "This post has no text to analyse. Video transcription is not enabled yet."
          : "Could not read this post. X may have changed its layout.";
        drawer.showError(why, btn);
        return;
      }

      btn.dataset.state = "loading";
      drawer.showLoading(payload, btn);

      try {
        const res = await requestAnalysis(payload);
        if (res && res.ok) {
          resultCache.set(article, { data: res.data, payload });
          drawer.showResult(res.data, payload, btn);
          btn.dataset.state = "done";
        } else {
          drawer.showError((res && res.error) || "Unknown error", btn);
          btn.dataset.state = "";
        }
      } catch (err) {
        // Usually means the service worker was restarted mid-flight.
        drawer.showError(String((err && err.message) || err), btn);
        btn.dataset.state = "";
      }
    });

    actions.appendChild(btn);
  }

  function scan(root) {
    (root || document).querySelectorAll(SELECTORS.tweet).forEach(injectButton);
  }

  // X is a single-page app: tweets stream in as you scroll and there is no page-load
  // event to hook. Watch the DOM instead.
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
