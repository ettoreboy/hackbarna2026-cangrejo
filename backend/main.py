"""FastAPI entry point.

Run: uvicorn backend.main:app --reload
Offline (no keys): ANALYZER_PROVIDER=fake uvicorn backend.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import Settings, get_settings
from backend.routers.analyze import router as analyze_router
from backend.schemas.analysis_schema import SCHEMA_VERSION, AnalyzeResponse
from backend.services.analyzer_base import AnalysisError, Analyzer
from backend.services.cache import TTLCache
from backend.services.fake_service import FakeAnalyzer

log = logging.getLogger("contextguard")


def build_analyzers(settings: Settings) -> dict[str, Analyzer]:
    """Every provider whose key is present, plus 'fake' when explicitly selected."""
    analyzers: dict[str, Analyzer] = {}
    if settings.nebius_configured:
        from backend.services.nebius_service import NebiusAnalyzer

        try:
            analyzers["nebius"] = NebiusAnalyzer(settings)
        except AnalysisError as exc:
            log.warning("nebius disabled: %s", exc)
    if settings.gemini_configured:
        from backend.services.gemini_service import GeminiAnalyzer

        try:
            analyzers["gemini"] = GeminiAnalyzer(settings)
        except AnalysisError as exc:
            log.warning("gemini disabled: %s", exc)
    if settings.analyzer_provider == "fake":
        analyzers["fake"] = FakeAnalyzer()
    return analyzers


def create_app(settings: Settings | None = None, analyzers: dict[str, Analyzer] | None = None) -> FastAPI:
    """Factory so tests can inject settings and analyzers."""
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.http = httpx.AsyncClient(follow_redirects=True)
        app.state.cache = TTLCache[AnalyzeResponse](ttl_seconds=settings.cache_ttl_seconds)
        app.state.analyzers = analyzers if analyzers is not None else build_analyzers(settings)
        if settings.analyzer_provider in app.state.analyzers:
            app.state.default_provider = settings.analyzer_provider
        elif app.state.analyzers:
            app.state.default_provider = sorted(app.state.analyzers)[0]
            log.warning("ANALYZER_PROVIDER=%s not available; defaulting to %s", settings.analyzer_provider, app.state.default_provider)
        else:
            app.state.default_provider = None
            log.warning("no analyzer configured; /analyze will return 503")
        try:
            yield
        finally:
            await app.state.http.aclose()

    app = FastAPI(
        title="ContextGuard Social API",
        version=f"0.2.0 (schema v{SCHEMA_VERSION})",
        description="Structured political-context and manipulation-signal analysis for social posts.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(chrome-extension://[a-z]{32}|https?://(localhost|127\.0\.0\.1)(:\d+)?)$",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
        allow_credentials=False,
    )
    app.include_router(analyze_router)
    return app


app = create_app()
