"""Author background retrieval chain: Wikipedia first, Brave web search as fallback.

Never raises. Any network or provider failure degrades to an empty list so the
analysis still runs (the prompt then tells the model not to invent biography).
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from backend.config import Settings
from backend.schemas.analysis_schema import Source

log = logging.getLogger(__name__)

WIKIPEDIA_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
# Wikimedia's robot policy (https://w.wiki/4wJS) returns 403 for a User-Agent with no contact
# details. Keep the URL and address in here or author background silently stops working.
USER_AGENT = (
    "ContextGuardSocial/0.2 "
    "(https://github.com/ettoreboy/hackbarna2026-cangrejo; contact@contextguard.example) "
    "httpx"
)


async def wikipedia_summary(client: httpx.AsyncClient, name: str, lang: str = "en") -> Source | None:
    """Return the Wikipedia lead summary for `name`, or None when no page exists."""
    title = quote(name.strip().replace(" ", "_"), safe="_")
    url = WIKIPEDIA_SUMMARY_URL.format(lang=lang, title=title)
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=5.0)
    except httpx.HTTPError as exc:
        log.warning("wikipedia request failed: %s", exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    # Disambiguation pages carry no usable biography.
    if data.get("type") == "disambiguation":
        return None
    extract = (data.get("extract") or "").strip()
    if not extract:
        return None
    page_url = (data.get("content_urls") or {}).get("desktop", {}).get("page") or url
    return Source(title=data.get("title") or name, url=page_url, snippet=extract[:1_200], provider="wikipedia")


async def brave_search(client: httpx.AsyncClient, query: str, api_key: str, count: int = 3) -> list[Source]:
    """Top web results from Brave Search. Empty list on any failure."""
    if not api_key:
        return []
    try:
        resp = await client.get(
            BRAVE_SEARCH_URL,
            params={"q": query, "count": count, "safesearch": "moderate", "text_decorations": "false"},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=6.0,
        )
    except httpx.HTTPError as exc:
        log.warning("brave request failed: %s", exc)
        return []
    if resp.status_code != 200:
        log.warning("brave returned %s", resp.status_code)
        return []
    results = (resp.json().get("web") or {}).get("results") or []
    out: list[Source] = []
    for r in results[:count]:
        url = r.get("url")
        if not url:
            continue
        out.append(
            Source(
                title=r.get("title") or url,
                url=url,
                snippet=(r.get("description") or "")[:600],
                provider="brave",
            )
        )
    return out


async def get_author_background(
    client: httpx.AsyncClient, settings: Settings, author_name: str, author_handle: str
) -> list[Source]:
    """Wikipedia summary if the author has a page; otherwise Brave (if configured); otherwise nothing."""
    wiki = await wikipedia_summary(client, author_name, settings.wikipedia_lang)
    if wiki is not None:
        return [wiki]
    if not settings.brave_configured:
        return []
    query = f"{author_name} @{author_handle} politician background"
    return await brave_search(client, query, settings.brave_api_key, settings.search_result_count)
