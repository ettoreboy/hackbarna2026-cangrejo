"""Canonical labels for communication signals and logical fallacies.

Single source of truth used by the prompt builder, the schema normaliser, tests, the eval
scripts and the fine-tune dataset generator. Definitions and detection cues live in
docs/TECHNIQUES.md; keep the two in sync.
"""

from __future__ import annotations

TACTICS: tuple[str, ...] = (
    "Outrage Farming",
    "Scapegoating",
    "Fear-mongering",
    "Dog Whistle",
    "Us-vs-Them Framing",
    "Dehumanization",
    "Emotional Bait",
    "Manufactured Urgency",
    "Cherry Picking",
    "Whataboutism",
    "Gish Gallop",
    "Astroturfing",
)

FALLACIES: tuple[str, ...] = (
    "False Dilemma",
    "Ad Hominem",
    "Hasty Generalization",
    "Slippery Slope",
    "Appeal to Fear",
    "Appeal to Emotion",
    "Straw Man",
    "Middle Ground",
    "Bandwagon",
    "Appeal to Authority",
    "Loaded Question",
    "No True Scotsman",
    "Post Hoc",
    "Motte and Bailey",
)

# Labels with reputational risk if wrong: the UI hides them below this confidence.
HIGH_RISK_TACTICS: frozenset[str] = frozenset({"Dog Whistle", "Scapegoating", "Dehumanization"})
HIGH_RISK_MIN_CONFIDENCE = 0.6

# Accepted spellings/synonyms → canonical. Lower-cased keys.
_SYNONYMS: dict[str, str] = {
    # tactics
    "outrage bait": "Outrage Farming",
    "rage bait": "Outrage Farming",
    "ragebait": "Outrage Farming",
    "fear mongering": "Fear-mongering",
    "fearmongering": "Fear-mongering",
    "fear appeal": "Fear-mongering",
    "dog-whistle": "Dog Whistle",
    "dog whistling": "Dog Whistle",
    "dogwhistle": "Dog Whistle",
    "in-group/out-group": "Us-vs-Them Framing",
    "in-group vs out-group": "Us-vs-Them Framing",
    "us vs them": "Us-vs-Them Framing",
    "us-vs-them": "Us-vs-Them Framing",
    "othering": "Us-vs-Them Framing",
    "tribalism": "Us-vs-Them Framing",
    "dehumanisation": "Dehumanization",
    "engagement bait": "Emotional Bait",
    "urgency": "Manufactured Urgency",
    "false urgency": "Manufactured Urgency",
    "cherry-picking": "Cherry Picking",
    "selective evidence": "Cherry Picking",
    "whataboutery": "Whataboutism",
    "tu quoque": "Ad Hominem",
    "manufactured consensus": "Astroturfing",
    # fallacies
    "false dichotomy": "False Dilemma",
    "either/or": "False Dilemma",
    "black-and-white thinking": "False Dilemma",
    "personal attack": "Ad Hominem",
    "overgeneralization": "Hasty Generalization",
    "over-generalization": "Hasty Generalization",
    "sweeping generalization": "Hasty Generalization",
    "appeal to popularity": "Bandwagon",
    "ad populum": "Bandwagon",
    "argumentum ad populum": "Bandwagon",
    "golden mean": "Middle Ground",
    "argument to moderation": "Middle Ground",
    "false cause": "Post Hoc",
    "post hoc ergo propter hoc": "Post Hoc",
    "strawman": "Straw Man",
    "straw-man": "Straw Man",
    "misplaced authority": "Appeal to Authority",
    "complex question": "Loaded Question",
    "appeal to pity": "Appeal to Emotion",
}

_CANONICAL_LOWER: dict[str, str] = {t.lower(): t for t in TACTICS + FALLACIES}


def normalize_label(name: str) -> str:
    """Map a model-produced label to its canonical spelling.

    Unknown labels are kept but prefixed with "Other: " so they are visible in eval output
    and can be promoted to the canonical list later.
    """
    key = name.strip().strip('"').lower()
    if key.startswith("other:"):
        key = key[6:].strip()
    if key in _CANONICAL_LOWER:
        return _CANONICAL_LOWER[key]
    if key in _SYNONYMS:
        return _SYNONYMS[key]
    return f"Other: {name.strip()}"


def is_canonical(name: str) -> bool:
    return name in TACTICS or name in FALLACIES


def prompt_block() -> str:
    """The allowed-vocabulary block inserted into the system prompt."""
    return (
        "ALLOWED communication_signals names: " + "; ".join(TACTICS) + ".\n"
        "ALLOWED logical_fallacies names: " + "; ".join(FALLACIES) + ".\n"
        'Use these spellings exactly. If a pattern is not listed, use "Other: <short name>".'
    )
