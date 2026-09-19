"""How hard the analyzer looks at a post's framing.

``standard`` is the shipped behaviour and must stay byte-identical to the prompts measured in
docs/EVAL.md: that document publishes a v0-against-v1 ablation, and editing the shared task or
RULES text would silently re-score it. Every instruction here is therefore appended, never
substituted, and only when rigor is ``strict``.

Why the knob exists. The analyzer was tuned in one direction only. Three strings push it toward
silence ("Empty list for a plainly informational post", "Do not pad the list", "Use Loaded
Language only when no more specific label applies") and none pushed it toward recall, while every
metric in backend/eval/metrics.py punished over-flagging and none punished under-flagging. On a
post that argued in policy register -- a ten-point plan called "pure symbolic politics", answered
with "watertight protection of our national borders and the immediate deportation of all threats"
-- it checked the claim, found it supported, and reported no rhetorical work at all.

The three patterns that post used are the three the standard cues miss:

- The threat is presupposed, not predicted. ``Fear-mongering``'s cue reads "predicts harm or
  catastrophe", so a danger the reader is simply expected to accept does not match it.
- People are filed under a risk category. ``Dehumanization``'s cue lists "vermin, parasites,
  filth or cargo", so "all threats" as a noun for human beings does not match it.
- The fix is total and guaranteed. Nothing in the vocabulary covered that, which is why
  ``False Solution`` was added to backend/prompts/taxonomy.py alongside this module.

The last bullet of the signals block is load-bearing in the other direction: strict rigor means
looking harder at posts that argue, never finding technique in posts that inform. It is what
keeps ``neutral_restraint`` at 1.00, and tests/fixtures/posts.json carries a policy-critique
control whose whole job is to prove it still holds.
"""

from __future__ import annotations

RIGOR_LEVELS: tuple[str, ...] = ("standard", "strict")
DEFAULT_RIGOR = "standard"

# Appended to every prompt that emits rhetorical_signals: the one-shot analysis prompt and the
# stage-1 discovery prompt. The extension's live path is /claims -> /analyze-claim, so leaving
# discovery out would change nothing in the drawer.
STRICT_SIGNALS_BLOCK = """
STRICT RIGOR — rhetorical_signals:
- List every technique the post uses, not only the clearest one. An argumentative post commonly carries four or five at once.
- A correct claim is not a neutral post. Judge the framing separately from the claim: a post can state a true fact and still be built to frighten, to divide, or to foreclose options. A "supported" verdict never suppresses a signal.
- A threat treated as settled fact is Fear-mongering. The threat need not be predicted out loud. If the post assumes a danger the reader is expected to accept without evidence — naming it as the thing a policy must "stop", or labelling people by the risk they are said to pose — that is Fear-mongering. Quote the phrase that carries the assumption.
- People named by a risk category rather than as people is Dehumanization: "threats", "cases", "illegals" used as a noun for human beings.
- A total, guaranteed fix for a complex problem is False Solution: "watertight", "completely seal", "once and for all", "simply deport".
- Rejecting one option while offering only one other is False Dilemma, even when the post never says "either/or".
- Quote the shortest span that carries each technique, and do not let one signal's quote contain another's. Two signals whose quotes overlap are merged into one before the reader sees them, so the longer quote silently costs you the shorter signal.
- Still return an empty list for a plainly informational post. Strict rigor means looking harder at posts that argue, never finding technique in posts that inform.
"""

# Appended to every prompt that writes missing_context: the one-shot analysis prompt and the
# stage-2 claim check. Both existing rules survive intact -- no intent-guessing, and nothing
# asserted about the world without EVIDENCE.
STRICT_CONTEXT_BLOCK = """
STRICT RIGOR — missing_context:
- When the post's persuasive force comes from its framing rather than its facts, say so in one clause, then name the missing fact as usual.
- Describe what the text does, never what the author wants. Write "The post treats terrorism as an ongoing certainty without citing an incident or a trend" — never "The author is trying to frighten readers."
- Naming a framing effect is not asserting a fact about the world. Everything you state about the world still requires EVIDENCE.
"""


def normalize_rigor(value: str | None) -> str:
    """Fall back to the default rather than raising: the routers already validate by pattern."""
    return value if value in RIGOR_LEVELS else DEFAULT_RIGOR


def suffix(rigor: str, *blocks: str) -> str:
    """Join the blocks that apply at this level. Empty string at ``standard``, always."""
    if normalize_rigor(rigor) == DEFAULT_RIGOR:
        return ""
    return "\n" + "\n".join(b.strip("\n") for b in blocks)
