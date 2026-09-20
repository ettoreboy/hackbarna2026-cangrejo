// The Unfold mark, as inline SVG: two facing pages, one open in front of the other.
//
// Both pages are drawn in `currentColor`, the right-hand one at reduced opacity, so the whole
// mark takes whatever accent colour X is currently using: set the colour property on the
// <svg> and both tones follow. That is why the original blues are not baked in here.
//
// viewBox is the artwork's real bounding box (x 87-913, y 160-840) plus 3%, computed from the
// path data rather than guessed, so the mark fills its box instead of floating inside the
// original 1000x1000 canvas. The shape is wider than it is tall, so height is derived from
// the requested width instead of being forced square.

(() => {
  const VIEW_BOX = "62 139 876 721";
  const ASPECT = 876 / 721;

  // Left page: solid accent.
  const FRONT =
    "M420.14,832.25l-303.51-95.08c-17.65-5.53-29.93-24.34-29.93-45.83V213.59c0-31.15,25.08-53.85," +
    "50.66-45.83l303.51,95.08c17.65,5.53,29.93,24.34,29.93,45.83v477.74c0,31.15-25.08,53.85-50.66,45.83Z";

  // Right page: the same colour, lighter, so the two read as one folded sheet.
  const BACK =
    "M579.86,832.25l303.51-95.08c17.65-5.53,29.93-24.34,29.93-45.83V213.59c0-31.15-25.08-53.85-50.66-45.83l-303.51," +
    "95.08c-17.65,5.53-29.93,24.34-29.93,45.83v477.74c0,31.15,25.08,53.85,50.66,45.83Z";

  window.UF_ICON = {
    /**
     * @param {number} width px; height follows the mark's own proportions
     * @param {string} [cls] extra class on the <svg>
     */
    svg(width, cls) {
      const height = Math.round(width / ASPECT);
      return (
        `<svg class="uf-icon${cls ? " " + cls : ""}" width="${width}" height="${height}" ` +
        `viewBox="${VIEW_BOX}" aria-hidden="true" focusable="false">` +
        `<path d="${FRONT}" fill="currentColor"/>` +
        `<path d="${BACK}" fill="currentColor" opacity=".45"/>` +
        `</svg>`
      );
    },
  };
})();
