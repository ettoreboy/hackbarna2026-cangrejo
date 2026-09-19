// Reads X's current theme off the page instead of guessing.
//
// X ships three themes (Default, Dim, Lights out) and switches them at runtime without
// touching prefers-color-scheme, so the media query is useless here. The body background is
// the one thing that always changes, so we read its luminance.

(() => {
  function luminance(rgb) {
    // Rec. 601 luma is close enough to decide light from dark.
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
  }

  // Returns [r, g, b, a], or null when the value is not a colour we can read.
  function parseColor(value) {
    const m = String(value || "").match(/-?\d+(?:\.\d+)?/g);
    if (!m || m.length < 3) return null;
    return [Number(m[0]), Number(m[1]), Number(m[2]), m.length > 3 ? Number(m[3]) : 1];
  }

  // X's six accent colours, in priority order of where we can read one reliably.
  // The compose button is filled with the accent; links inside tweet text use it as their
  // foreground. Both disappear at some viewport widths, hence the chain.
  const ACCENT_SOURCES = [
    ['[data-testid="SideNav_NewTweet_Button"]', "backgroundColor"],
    ['[data-testid="tweetButtonInline"]', "backgroundColor"],
    ['[data-testid="tweetText"] a', "color"],
    ['[role="link"][style*="color"]', "color"],
  ];

  const DEFAULT_ACCENT = "rgb(29, 155, 240)"; // X blue, the out-of-the-box choice

  // Greys and near-white/near-black are never the accent; they are just text or chrome.
  //
  // Saturation, not a raw channel spread: X's muted grey rgb(83, 100, 113) has a spread of 30
  // and would pass a naive threshold, but its saturation is only 0.27. Every one of X's six
  // accents sits at 0.66 or above, the lowest being purple.
  function isAccent(c) {
    const max = Math.max(c[0], c[1], c[2]);
    const min = Math.min(c[0], c[1], c[2]);
    if (max < 40) return false; // near-black
    return (max - min) / max >= 0.45;
  }

  window.UF_THEME = {
    // The accent X is set to, as an "rgb(r, g, b)" string. Falls back to X blue.
    accent() {
      try {
        for (const [selector, prop] of ACCENT_SOURCES) {
          for (const el of document.querySelectorAll(selector)) {
            const c = parseColor(getComputedStyle(el)[prop]);
            if (c && c[3] !== 0 && isAccent(c)) return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
          }
        }
      } catch {
        /* fall through to the default */
      }
      return DEFAULT_ACCENT;
    },

    // "light" | "dark", from whatever X is currently painting behind the timeline.
    current() {
      try {
        // A fully transparent background tells us nothing, so walk outwards until something
        // is actually painted. "Lights out" is pure black, which is opaque and reads as dark.
        for (const el of [document.body, document.documentElement]) {
          if (!el) continue;
          const c = parseColor(getComputedStyle(el).backgroundColor);
          if (!c || c[3] === 0) continue;
          return luminance(c) > 0.5 ? "light" : "dark";
        }
      } catch {
        /* fall through to the default */
      }
      return "light";
    },

    // Calls back with (mode, accent) whenever either changes while the card is open.
    // X applies both from its Display settings without reloading the page.
    onChange(fn) {
      let lastMode = this.current();
      let lastAccent = this.accent();
      const check = () => {
        const mode = this.current();
        const accent = this.accent();
        if (mode !== lastMode || accent !== lastAccent) {
          lastMode = mode;
          lastAccent = accent;
          fn(mode, accent);
        }
      };
      const observer = new MutationObserver(check);
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["style", "class"],
      });
      if (document.body) {
        observer.observe(document.body, { attributes: true, attributeFilter: ["style", "class"] });
      }
      return () => observer.disconnect();
    },
  };
})();

