"""Step 2: web evidence. Brave Search, cache-first, budget-guarded. Never raises.

``gather_evidence`` is the single entry point every flow uses. It tries the extracted claim
first, falls back to a search on the post itself, and only then to a provider's canned
results. The reader always gets something to click: a post with no checkable claim still
deserves related reading, and an empty panel reads as a broken extension.
"""

from __future__ import annotations

import re

import httpx

from backend.config import Settings
from backend.schemas.analysis_schema import MainClaim, QuotedPost, Source
from backend.services.background_service import brave_search
from backend.services.search_cache import SearchCache

_MAX_QUERY_CHARS = 300

# A raw post makes a poor query: t.co links, @mentions and # marks match nothing on the web.
_URL_RE = re.compile(r"https?://\S+|\bwww\.\S+")
_HANDLE_RE = re.compile(r"(?<![\w/])@\w+")
_HASH_RE = re.compile(r"#(?=\w)")


def query_from_post(post_text: str) -> str:
    """The post reduced to something worth sending to a search engine. May be empty."""
    text = _URL_RE.sub(" ", post_text)
    text = _HANDLE_RE.sub(" ", text)
    text = _HASH_RE.sub("", text)
    return " ".join(text.split())[:_MAX_QUERY_CHARS]


def search_text(post_text: str, quoted: QuotedPost | None = None) -> str:
    """What the post-level search should run on: the post, plus the post it quotes.

    A quote-tweet keeps the reaction and gives away the substance. "45% across the entire East.
    The East is blue!" searches for nothing; the Forsa numbers in the quoted post are the whole
    query. The author's own words still come first, because they set the framing, and
    ``query_from_post`` truncates at 300 characters.
    """
    if quoted is None or not quoted.text.strip():
        return post_text
    return f"{post_text}\n{quoted.text}"


async def search_claim(
    client: httpx.AsyncClient, settings: Settings, claim: MainClaim, cache: SearchCache | None = None
) -> list[Source]:
    """Top web results for the claim text. Empty when the claim is absent, no key, over budget, or on error."""
    if not claim.found or not claim.text.strip() or not settings.brave_configured:
        return []
    query = claim.text.strip()[:_MAX_QUERY_CHARS]
    return await brave_search(client, query, settings.brave_api_key, settings.evidence_result_count, cache, settings.brave_budget)


async def gather_evidence(
    client: httpx.AsyncClient,
    settings: Settings,
    claim: MainClaim | None,
    post_text: str,
    cache: SearchCache | None = None,
    offline=None,
    handle: str = "",
) -> list[Source]:
    """Web results related to this post, in order of preference: claim, post, canned.

    The post-text search costs at most one extra live Brave call, and only when the claim
    search found nothing. The disk cache and BRAVE_BUDGET guard inside ``brave_search`` both
    still apply, so this cannot run away with the prepaid quota.
    """
    if claim is not None:
        evidence = await search_claim(client, settings, claim, cache)
        if evidence:
            return evidence

    if settings.brave_configured:
        query = query_from_post(post_text)
        if query:
            evidence = await brave_search(
                client, query, settings.brave_api_key, settings.evidence_result_count, cache, settings.brave_budget
            )
            if evidence:
                return evidence

    # Canned results so every verdict stays reachable with no BRAVE_API_KEY. Only the fake
    # provider defines this; real providers stay empty and the verdict stays "unverifiable".
    if offline is not None:
        return offline(claim, handle)
    return []
