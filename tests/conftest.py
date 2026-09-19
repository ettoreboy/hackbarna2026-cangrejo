"""Shared fixtures: fake analyzer, app factory with injected settings, ASGI client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio

from backend.config import Settings
from backend.main import create_app
from backend.services.fake_service import FakeAnalyzer

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "posts.json").read_text())
WIKI_RE = r"https://en\.wikipedia\.org/api/rest_v1/page/summary/.*"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ANALYZER_PROVIDER": "fake",
        "GEMINI_API_KEY": "",
        "NEBIUS_API_KEY": "",
        "BRAVE_API_KEY": "",
        "CACHE_TTL_SECONDS": 3600,
        "SEARCH_CACHE_PATH": "",
        # Both caches stay in memory: a test must never read a row an earlier run wrote.
        "RESPONSE_CACHE_PATH": "",
        # respx raises on an unmocked host, so a fixture that gains a URL would otherwise
        # break tests that have nothing to do with links. Switch it on per test.
        "LINK_FETCH_ENABLED": False,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def wiki_ok(title: str, extract: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "type": "standard",
            "title": title,
            "extract": extract,
            "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"}},
        },
    )


def brave_ok(*results: tuple[str, str, str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"web": {"results": [{"title": t, "url": u, "description": d} for t, u, d in results]}},
    )


class _lifespan:
    """ASGITransport does not run lifespan events; drive them manually."""

    def __init__(self, app):
        self.app = app
        self.cm = None

    async def __aenter__(self):
        self.cm = self.app.router.lifespan_context(self.app)
        await self.cm.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self.cm.__aexit__(*exc)


@pytest.fixture
def fake_analyzer() -> FakeAnalyzer:
    return FakeAnalyzer()


async def _client_for(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c, _lifespan(app):
        yield c


@pytest_asyncio.fixture
async def client(fake_analyzer: FakeAnalyzer):
    app = create_app(settings=make_settings(), analyzers={"fake": fake_analyzer})
    async for c in _client_for(app):
        yield c


@pytest_asyncio.fixture
async def client_with_brave(fake_analyzer: FakeAnalyzer):
    app = create_app(settings=make_settings(BRAVE_API_KEY="brave-test"), analyzers={"fake": fake_analyzer})
    async for c in _client_for(app):
        yield c


@pytest_asyncio.fixture
async def client_no_provider():
    app = create_app(settings=make_settings(ANALYZER_PROVIDER="nebius"), analyzers={})
    async for c in _client_for(app):
        yield c
