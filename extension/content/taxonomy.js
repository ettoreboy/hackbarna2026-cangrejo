// Canonical label vocabulary, mirrored from backend/prompts/taxonomy.py.
// The backend already normalises every label before it reaches us, so this file is only
// used for display decisions (which badges to hide, which to render muted).
// If the Python list changes, change this one too - that is a two-person decision.

(() => {
  const HIGH_RISK = new Set(["Dog Whistle", "Scapegoating", "Dehumanization"]);
  const HIGH_RISK_MIN_CONFIDENCE = 0.6;

  window.CG_TAXONOMY = {
    HIGH_RISK,
    HIGH_RISK_MIN_CONFIDENCE,

    // Labels the model invented rather than picked from the list arrive prefixed "Other: ".
    isUncategorised(name) {
      return String(name || "").startsWith("Other: ");
    },

    // Reputational risk if we are wrong, so hide these below the confidence floor.
    // Contract: docs/API.md, "Field guide for rendering".
    shouldHideSignal(signal) {
      if (!signal || !signal.name) return true;
      return HIGH_RISK.has(signal.name) && Number(signal.confidence) < HIGH_RISK_MIN_CONFIDENCE;
    },
  };
})();
