"""Pages the post links to, fetched and reduced to text.

The other kind of pointed-at context, the quoted post, needs no code here: the extension reads
it out of the DOM and it arrives in the request. Only links cost a network round trip, and the
host is named by untrusted content, so this module is mostly bounds.

What each bound protects:

- ``is_fetchable`` rejects anything that is not http(s) and any literal private, loopback,
  link-local, reserved, multicast or unspecified address. That is what keeps a post from
  pointing us at ``http://127.0.0.1:8000`` or at the cloud metadata address 169.254.169.254.
- Redirects are followed by hand, two hops at most, re-checking every ``Location``. The shared
  client in backend/main.py is built with ``follow_redirects=True`` for Wikipedia and Brave;
  leaving that on here would make the guard decorative, because an attacker would simply serve
  a 302 to 127.0.0.1. ``max_redirects`` can only be set at construction, so per-request
  ``follow_redirects=False`` plus this loop is the way to bound the hops.
- The body is streamed and cut at LINK_MAX_BYTES. A plain ``get`` reads the whole response into
  memory before you can truncate it.
- The whole phase sits inside one wall-clock ``asyncio.wait_for``.

Deliberately not done: resolving the hostname and pinning the connection to that IP, which is
what actually closes DNS rebinding. It is ~40 lines, still TOCTOU-racy, and out of proportion
to a laptop-local server whose CORS is locked to the extension.

Never raises, on the same principle as background_service: a link that fails is a link the
reader does not get, not a 500. The catch is ``Exception``, not ``httpx.HTTPError`` — a captive
portal already produced a ValueError once, and HTMLParser on malformed markup is the same class
of surprise.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from html.parser import HTMLParser
from typing import Sequence
from urllib.parse import urlparse

import httpx

from backend.config import Settings
from backend.schemas.analysis_schema import LinkedPage, QuotedPost
from backend.services.search_cache import SearchCache

log = logging.getLogger(__name__)

# Trailing punctuation is part of the sentence, not of the URL.
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+")
_TRAILING = ".,;:!?'\"»”’"

_MAX_HOPS = 2
_HEADERS = {
    "user-agent": "Unfold/0.3 (media-literacy research; +https://github.com/unfold)",
    "accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8",
    "accept-language": "en,de;q=0.8",
}
_READABLE_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

# Links back into X are not articles. An unauthenticated fetch of x.com returns a JavaScript
# shell, and a linked status is a quoted post by another name. t.co is deliberately absent:
# it is X's shortener and the destination behind it is exactly what we want.
_SELF_HOSTS = {"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
_MEDIA_HOSTS = {"pic.x.com", "pic.twitter.com", "pbs.twimg.com", "video.twimg.com", "t.me"}

_BLOCKED_HOSTS = {"localhost", "ip6-localhost", "ip6-loopback"}
_BLOCKED_SUFFIXES = (".localhost", ".internal", ".local", ".home.arpa")


# --------------------------------------------------------------------------- selection


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_fetchable(url: str) -> bool:
    """Whether this URL may be fetched at all. Applied again to every redirect hop."""
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    # An allowlist, not a blocklist: it also kills a file: or gopher: Location header.
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    if not host:
        return False
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A name. Resolving it here would not help; see the module docstring.
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def extract_urls(post_text: str, links: Sequence[str] = (), limit: int = 2) -> list[str]:
    """The URLs worth fetching, client-supplied first, then whatever the text carries.

    The client's list wins because X renders a link as truncated display text
    ("bamf.example/report-2…"): the fetchable href only exists on the anchor. The regex pass is
    the fallback for callers that are not the extension — scripts, tests, /compare.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in [*links, *_URL_RE.findall(post_text or "")]:
        url = (raw or "").strip().rstrip(_TRAILING)
        if not url or not is_fetchable(url):
            continue
        host = _host(url)
        if host in _SELF_HOSTS or host in _MEDIA_HOSTS:
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def urls_for(req_post_text: str, links: Sequence[str], quoted: QuotedPost | None, limit: int) -> list[str]:
    """Links from the post and from the post it quotes, in that order."""
    quoted_text = quoted.text if quoted is not None else ""
    return extract_urls(f"{req_post_text}\n{quoted_text}", links, limit)


# --------------------------------------------------------------------------- extraction


class _PageText(HTMLParser):
    """Title, description and visible text.

    The skip stack is not tidiness. html.parser enters CDATA mode for <script> and <style> and
    still calls handle_data with their contents, so without it the page's JavaScript source
    lands in the prompt: the largest injection surface on the page, and pure token waste.
    Comments are dropped by the base class, which never forwards them.
    """

    _SKIP = {"script", "style", "noscript", "template", "svg", "nav", "footer", "header", "form", "aside", "iframe"}
    _BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_title = ""
        self.description = ""
        self.parts: list[str] = []
        self._title_parts: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs}
            name = (a.get("property") or a.get("name") or "").lower()
            if name in ("og:title", "twitter:title") and not self.og_title:
                self.og_title = a.get("content", "")
            elif name in ("description", "og:description", "twitter:description") and not self.description:
                self.description = a.get("content", "")
        elif tag in self._BREAK:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self._BREAK:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self._title_parts.append(data)
        else:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return (self.og_title or "".join(self._title_parts)).strip()


def parse_html(html: str) -> tuple[str, str]:
    """(title, text) for a page. Returns ("", "") rather than raising on malformed markup."""
    parser = _PageText()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # malformed markup is the normal case, not the exception
        log.debug("html parse stopped early: %s", exc)
    body = " ".join("".join(parser.parts).split())
    # The meta description is usually the best one-line summary on the page, so it leads.
    description = " ".join(parser.description.split())
    text = f"{description} {body}".strip() if description else body
    return parser.title, text


# --------------------------------------------------------------------------- fetching


def _cache_key(url: str) -> str:
    """Namespaced: SearchCache.normalise only lowercases, so a bare URL would collide with a
    Brave query in the same table."""
    return f"link:{url.rstrip('/')}"


async def _get(client: httpx.AsyncClient, settings: Settings, url: str) -> LinkedPage | None:
    current = url
    for _ in range(_MAX_HOPS + 1):
        if not is_fetchable(current):
            return None
        async with client.stream(
            "GET",
            current,
            follow_redirects=False,
            timeout=settings.link_timeout_seconds,
            headers=_HEADERS,
        ) as resp:
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                if not location:
                    return None
                current = str(httpx.URL(current).join(location))
                continue
            if resp.status_code >= 400:
                return None
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            # Checked from the headers, before a single body byte is read.
            if ctype not in _READABLE_TYPES:
                return None
            encoding = resp.encoding or "utf-8"
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= settings.link_max_bytes:
                    break
        raw = b"".join(chunks)[: settings.link_max_bytes]
        body = raw.decode(encoding, errors="replace")
        if ctype == "text/plain":
            title, text = "", " ".join(body.split())
        else:
            title, text = parse_html(body)
        return LinkedPage(
            url=url,
            final_url=current,
            title=title[:300],
            text=text[: settings.link_max_chars],
        )
    log.info("link fetch gave up after %d redirects: %s", _MAX_HOPS, url)
    return None


async def _fetch_one(
    client: httpx.AsyncClient, settings: Settings, url: str, cache: SearchCache | None
) -> LinkedPage | None:
    if cache is not None:
        hit = cache.get(_cache_key(url))
        if hit:
            try:
                return LinkedPage(**hit[0])
            except Exception:
                pass  # a row from an older shape; refetch rather than guess

    try:
        page = await asyncio.wait_for(_get(client, settings, url), settings.link_timeout_seconds)
    except Exception as exc:
        log.info("link fetch failed for %s: %s", url, exc)
        return None

    if page is None or not page.text.strip():
        # Never cache a miss. This cache has no expiry, so one bad minute would pin the URL to
        # "no content" for the rest of the event — the same reason brave_search skips empties.
        return None

    if cache is not None:
        try:
            cache.put(_cache_key(url), [page.model_dump()])
        except Exception as exc:
            log.debug("link cache write failed for %s: %s", url, exc)
    return page


async def fetch_links(
    client: httpx.AsyncClient,
    settings: Settings,
    urls: Sequence[str],
    cache: SearchCache | None = None,
) -> list[LinkedPage]:
    """Fetch every URL, concurrently, under one wall-clock ceiling. Never raises.

    ``record_live_call`` is never touched here: that table is the prepaid Brave meter behind
    BRAVE_BUDGET and /health.brave_live_calls, and polluting it would silently disable evidence
    search mid-demo.
    """
    if not settings.link_fetch_enabled or not urls:
        return []

    async def _all() -> list[LinkedPage]:
        pages = await asyncio.gather(*(_fetch_one(client, settings, u, cache) for u in urls))
        return [p for p in pages if p is not None]

    try:
        return await asyncio.wait_for(_all(), settings.link_total_seconds)
    except Exception as exc:
        log.info("link phase abandoned after %.1fs: %s", settings.link_total_seconds, exc)
        return []
