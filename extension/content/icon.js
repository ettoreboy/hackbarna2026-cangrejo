// The Unfold mark, as inline SVG.
//
// Both shapes are drawn in `currentColor`, the back one at reduced opacity, so the whole
// icon takes whatever accent colour X is currently using: set `color` on the <svg> and both
// tones follow. That is why the original blues are not baked in here.
//
// viewBox is the artwork's real bounding box (x 293-683, y 249-744) squared off with 4%
// padding, so the mark fills its box instead of floating in the original 1000x1000 canvas.

(() => {
  const VIEW_BOX = "220 229 535 535";

  // Back sheet: the page being unfolded. Lighter, so it reads as behind.
  const BACK =
    "M652.13,341.91l-250.1,21.46c-5.28.45-6.3-7.3-1.09-8.24l179.37-32.17c6.3-1.13,10.88-6.61," +
    "10.88-13.01v-31.31c0-25.27-8.42-29.87-25.43-21.71l-209.63,88-55.32,25.03c-4.82,2.28-7.9," +
    "7.13-7.9,12.47v106.19l352.35,151.9c18.08,7.79,37.87-6.25,37.87-26.87v-242.95c0-17.51-14.57-31.03-31.01-28.79Z";

  // Front sheet: solid accent.
  const FRONT =
    "M308.18,369.1c-8.02-1.25-15.26,4.94-15.26,13.06v228.89c0,13.6,0,29.14,17.73,34.2l256.27," +
    "89.85c28.54,9.3,65.95-.28,65.95-34.2v-246.53c0-9.36-3.12-18.22-8.57-25.37-6.02-7.9-15.21-12.78-25.03-14.31l-291.1-45.57Z";

  window.UF_ICON = {
    /**
     * @param {number} size  px, square
     * @param {string} [cls] extra class on the <svg>
     */
    svg(size, cls) {
      return (
        `<svg class="uf-icon${cls ? " " + cls : ""}" width="${size}" height="${size}" ` +
        `viewBox="${VIEW_BOX}" aria-hidden="true" focusable="false">` +
        `<path d="${BACK}" fill="currentColor" opacity=".45"/>` +
        `<path d="${FRONT}" fill="currentColor"/>` +
        `</svg>`
      );
    },
  };
})();
