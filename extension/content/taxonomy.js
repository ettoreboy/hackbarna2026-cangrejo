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

  // What each signal name means, in one line, for the card's hover definition. Mirrors CUES in
  // backend/prompts/taxonomy.py and scripts/check_extension.py compares the two: a badge on its
  // own is an accusation in jargon, and a reader who does not know what "Dog Whistle" means
  // cannot agree or disagree with it.
  const MEANINGS = {
    "Loaded Language": "An emotionally charged word chosen over a neutral one.",
    "Outrage Farming": "Framed to provoke sharing and anger rather than to inform.",
    "Scapegoating": "One group blamed for a complex problem.",
    "Fear-mongering": "Predicts harm or catastrophe to move the reader.",
    "Dog Whistle": "Coded phrasing that signals something extra to an in-group.",
    "Us-vs-Them Framing": "Splits people into a virtuous us and a hostile them.",
    "Dehumanization": "People described as vermin, parasites, filth or cargo.",
    "Emotional Bait": "Asks for a reaction, share or outrage rather than making a point.",
    "Manufactured Urgency": "A deadline or now-or-never framing that is not real.",
    "Cherry Picking": "One favourable number or case stands in for the whole picture.",
    "Whataboutism": "Deflects by pointing at someone else's conduct.",
    "Gish Gallop": "Many separate assertions at once, too many to answer.",
    "Astroturfing": "Presents an organised campaign as spontaneous public feeling.",
    "False Dilemma": "Only two options offered when more exist.",
    "False Solution": "A complex problem is given a total, guaranteed fix.",
    "Ad Hominem": "Attacks the person instead of the argument.",
    "Hasty Generalization": "A sweeping rule drawn from one or two cases.",
    "Slippery Slope": "One step is said to lead inevitably to an extreme outcome.",
    "Straw Man": "Argues against a distorted version of the other side's position.",
    "Middle Ground": "Treats the midpoint between two claims as automatically correct.",
    "Bandwagon": "Everyone thinks this, therefore it is true.",
    "Appeal to Authority": "Cites status or a title in place of evidence.",
    "Loaded Question": "A question whose phrasing assumes the disputed fact.",
    "No True Scotsman": "Redefines the group to exclude an inconvenient example.",
    "Post Hoc": "Treats sequence as proof of cause.",
    "Motte and Bailey": "Advances a bold claim, retreats to a modest one when challenged.",
  };

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

    // One plain line explaining the label, or "" for an invented one we have no definition for.
    meaning(name) {
      return MEANINGS[String(name || "")] || "";
    },
  };
})();
