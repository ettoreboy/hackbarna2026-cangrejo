// Display rules for the claim verdict and the rhetorical signal labels.
// Mirrors backend/prompts/taxonomy.py and the Verdict literal in schemas/analysis_schema.py.
//
// The backend normalises every label before it reaches us, so this file only decides how
// something looks, never whether it is valid.
//
// v3 merged manipulation tactics and logical fallacies into one vocabulary and dropped the
// per-signal confidence score, so there is no confidence threshold to filter on any more.

(() => {
  // Wording and colour for each verdict. The verdict is about the extracted claim only -
  // never about the post - so no label here says "true", "false" or "fake".
  const VERDICTS = {
    supported:           { label: "Supported",           tone: "green" },
    partially_supported: { label: "Partially supported", tone: "amber" },
    unsupported:         { label: "Unsupported",         tone: "red"   },
    unverifiable:        { label: "Unverifiable",        tone: "grey"  },
    no_factual_claim:    { label: "No factual claim",    tone: "grey"  },
  };

  const FALLBACK = { label: "Unverifiable", tone: "grey" };

  // Reputational risk if the model is wrong about these. backend/prompts/taxonomy.py asks
  // the client to render them cautiously; we mark them rather than hide them, since v3
  // gives us no confidence value to threshold on.
  const HIGH_RISK = new Set(["Dog Whistle", "Scapegoating", "Dehumanization"]);

  window.UF_TAXONOMY = {
    verdict(name) {
      return VERDICTS[String(name || "")] || FALLBACK;
    },

    // Labels the model invented rather than picked from the list arrive prefixed "Other: ".
    isUncategorised(name) {
      return String(name || "").startsWith("Other: ");
    },

    isHighRisk(name) {
      return HIGH_RISK.has(String(name || ""));
    },
  };
})();
