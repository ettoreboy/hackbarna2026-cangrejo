// Content script: finds tweets, injects the 🛡️ button, scrapes the post, asks the background worker.
// All X-specific selectors live in SELECTORS so a DOM change is a one-place fix.

(() => {
  if (window.__contextGuardLoaded) return;
  window.__contextGuardLoaded = true;

  const SELECTORS = {
    tweet: 'article[data-testid="tweet"]',
    text: '[data-testid="tweetText"]',
    userName: '[data-testid="User-Name"]',
    actions: '[role="group"]',
    statusLink: 'a[href*="/status/"]',
  };
  const MARK = "data-cg-injected";

  const overlay = new window.ContextGuardOverlay();

  function extractPost(article) {
    const textEl = article.querySelector(SELECTORS.text);
    const post_text = textEl ? textEl.innerText.trim() : "";

    // User-Name block contains display name and "@handle" as separate spans.
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

    const link = article.querySelector(SELECTORS.statusLink);
    const post_url = link ? new URL(link.getAttribute("href"), location.origin).toString() : undefined;

    return { author_handle, author_name, post_text, platform: "x", post_url };
  }

  function injectButton(article) {
    if (article.hasAttribute(MARK)) return;
    const actions = article.querySelector(SELECTORS.actions);
    if (!actions) return;
    article.setAttribute(MARK, "1");

    const btn = document.createElement("button");
    btn.className = "cg-verify-btn";
    btn.type = "button";
    btn.title = "Verify & contextualize this post";
    btn.innerHTML = "🛡️ <span>Context</span>";

    btn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const payload = extractPost(article);
      if (!payload.post_text || !payload.author_handle) {
        overlay.showError("Could not read this post. X may have changed its layout.");
        return;
      }
      btn.dataset.state = "loading";
      overlay.showLoading(payload);
      try {
        const res = await chrome.runtime.sendMessage({ type: "ANALYZE", payload });
        if (res?.ok) {
          overlay.showResult(res.data, payload);
          btn.dataset.state = "done";
        } else {
          overlay.showError(res?.error || "Unknown error");
          btn.dataset.state = "";
        }
      } catch (err) {
        overlay.showError(String(err));
        btn.dataset.state = "";
      }
    });

    actions.appendChild(btn);
  }

  function scan(root = document) {
    root.querySelectorAll(SELECTORS.tweet).forEach(injectButton);
  }

  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        if (node.matches?.(SELECTORS.tweet)) injectButton(node);
        else scan(node);
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
  scan();
})();
