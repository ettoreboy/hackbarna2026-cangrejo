"""Author background retrieval and the shared Brave search client.

Wikipedia first; Brave only as a fallback and only when BACKGROUND_BRAVE_FALLBACK is on
(off by default: Brave is prepaid and unknown authors are common). Never raises. Any network
or provider failure degrades to an empty list so the analysis still runs.

All Brave traffic goes through ``brave_search``, which consults the disk cache first, counts
live calls, and refuses once BRAVE_BUDGET is reached.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from backend.config import Settings
from backend.schemas.analysis_schema import Source
from backend.services.search_cache import SearchCache

log = logging.getLogger(__name__)

WIKIPEDIA_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Wikimedia's robot policy (https://w.wiki/4wJS) returns 403 for a User-Agent with no contact
# details. Keep the URL and address in here or author background silently stops working.
USER_AGENT = (
    "Unfold/0.3 "
    "(https://github.com/ettoreboy/hackbarna2026-cangrejo; contact@unfold.example) "
    "httpx"
)


async def wikipedia_summary(client: httpx.AsyncClient, name: str, lang: str = "en") -> Source | None:
    """Return the Wikipedia lead summary for `name`, or None when no page exists."""
    title = quote(name.strip().replace(" ", "_"), safe="_")
    url = WIKIPEDIA_SUMMARY_URL.format(lang=lang, title=title)
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=5.0)
        if resp.status_code != 200:
            return None
        # A captive portal answers 200 with an HTML login page. json() then raises ValueError,
        # which is neither an httpx.HTTPError nor an AnalysisError, so it used to escape the
        # router as a raw 500 traceback. Conference wifi is exactly where this happens.
        data = resp.json()
    except httpx.HTTPError as exc:
        log.warning("wikipedia request failed: %s", exc)
        return None
    except ValueError:
        log.warning("wikipedia returned a non-JSON body (captive portal?)")
        return None
    if data.get("type") == "disambiguation":
        return None
    extract = (data.get("extract") or "").strip()
    if not extract:
        return None
    page_url = (data.get("content_urls") or {}).get("desktop", {}).get("page") or url
    return Source(title=data.get("title") or name, url=page_url, snippet=extract[:1_200], provider="wikipedia")


async def brave_search(
    client: httpx.AsyncClient,
    query: str,
    api_key: str,
    count: int = 3,
    cache: SearchCache | None = None,
    budget: int | None = None,
) -> list[Source]:
    """Top web results from Brave, cache-first and budget-guarded. Empty list on any failure."""
    if not api_key:
        return []
    if cache is not None:
        hit = cache.get(query)
        if hit is not None:
            return [Source(**item) for item in hit][:count]
        if budget is not None and cache.live_calls() >= budget:
            log.warning("brave budget of %d live calls reached; skipping search for %r", budget, query[:60])
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
        # Counted only on a served request. Counting before the status check meant a 429 or a
        # 5xx still spent budget we had paid for and never received results for.
        log.warning("brave returned %s", resp.status_code)
        return []
    if cache is not None:
        cache.record_live_call(query)
    try:
        results = (resp.json().get("web") or {}).get("results") or []
    except ValueError:
        log.warning("brave returned a non-JSON body (captive portal?)")
        return []
    out: list[Source] = []
    for r in results[:count]:
        url = r.get("url")
        if not url:
            continue
        out.append(Source(title=r.get("title") or url, url=url, snippet=(r.get("description") or "")[:600], provider="brave"))
    # An empty result is never cached. The cache has no expiry during the event, so caching a
    # miss would pin that query to "no evidence" for the rest of the hackathon.
    if cache is not None and out:
        cache.put(query, [s.model_dump() for s in out])
    return out


async def get_author_background(
    client: httpx.AsyncClient,
    settings: Settings,
    author_name: str,
    author_handle: str,
    cache: SearchCache | None = None,
) -> list[Source]:
    """Wikipedia summary if the author has a page; otherwise Brave only if the fallback is enabled."""
    wiki = await wikipedia_summary(client, author_name, settings.wikipedia_lang)
    if wiki is not None:
        return [wiki]
    if not settings.brave_configured or not settings.background_brave_fallback:
        return []
    query = f"{author_name} @{author_handle} politician background"
    return await brave_search(
        client, query, settings.brave_api_key, settings.search_result_count, cache, settings.brave_budget
    )
