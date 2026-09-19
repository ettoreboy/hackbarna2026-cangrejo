"""Snap a model-produced quote back onto the exact characters of the post.

Models reproduce a quote faithfully in meaning but normalise typography: a non-breaking hyphen
(U+2011) becomes "-", a curly apostrophe becomes "'", a narrow no-break space becomes " ".
A plain substring test then fails, and the client cannot highlight the span it was given.

``snap_quote`` finds the span by comparing folded text and returns the *original* slice of the
post, so what reaches the client is always literally present in the post.
"""

from __future__ import annotations

import re
import unicodedata

_DASHES = "‐‑‒–—―−"
_SQUOTES = "‘’‚‛′"
_DQUOTES = "“”„‟″"
_SPACES = "       "

_TRANSLATION = {ord(c): "-" for c in _DASHES}
_TRANSLATION |= {ord(c): "'" for c in _SQUOTES}
_TRANSLATION |= {ord(c): '"' for c in _DQUOTES}
_TRANSLATION |= {ord(c): " " for c in _SPACES}
_TRANSLATION |= {ord("…"): "..."}

_WS = re.compile(r"\s+")
# Trailing junk a model adds when it trims: an ellipsis, a dangling quote, stray punctuation.
_TRIM = " \t\n\r\"'`.,;:!?…-–—"


def fold(text: str) -> str:
    """Normalise typography and whitespace for comparison only."""
    text = unicodedata.normalize("NFKC", text)
    return _WS.sub(" ", text.translate(_TRANSLATION)).strip()


def snap_quote(post: str, quote: str, min_chars: int = 12) -> str | None:
    """Return the exact substring of `post` that `quote` refers to, or None if it is not there.

    Tries, in order: an exact match, a typography-folded match, and a folded match after
    trimming the ellipses and stray punctuation models add when they shorten a span.
    """
    q = quote.strip()
    if not q:
        return None
    if q in post:
        return q

    folded_post = fold(post)
    # Map each character of the folded post back to an index in the original.
    index_map: list[int] = []
    buf: list[str] = []
    prev_space = False
    for i, ch in enumerate(unicodedata.normalize("NFKC", post)):
        mapped = ch.translate(_TRANSLATION)
        for m in mapped:
            if m.isspace():
                if prev_space or not buf:
                    continue
                prev_space = True
                buf.append(" ")
                index_map.append(i)
            else:
                prev_space = False
                buf.append(m)
                index_map.append(i)
    rebuilt = "".join(buf).strip()
    # Recompute offsets after the strip above.
    lead = len(buf) - len("".join(buf).lstrip())
    index_map = index_map[lead : lead + len(rebuilt)]
    if rebuilt != folded_post:
        folded_post = rebuilt

    for candidate in (fold(q), fold(q).strip(_TRIM)):
        if len(candidate) < min_chars:
            continue
        pos = folded_post.find(candidate)
        if pos == -1:
            continue
        start = index_map[pos]
        end_idx = pos + len(candidate) - 1
        end = index_map[end_idx] + 1 if end_idx < len(index_map) else len(post)
        return post[start:end]
    return None
