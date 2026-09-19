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

  window.CG_THEME = {
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

    // Calls back whenever the user switches theme while the card is open.
    onChange(fn) {
      let last = this.current();
      const check = () => {
        const now = this.current();
        if (now !== last) {
          last = now;
          fn(now);
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
