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


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ANALYZER_PROVIDER": "fake",
        "GEMINI_API_KEY": "",
        "NEBIUS_API_KEY": "",
        "BRAVE_API_KEY": "",
        "CACHE_TTL_SECONDS": 3600,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


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
