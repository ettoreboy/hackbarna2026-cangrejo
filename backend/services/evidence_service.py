"""Step 2: web evidence for the extracted claim. Brave Search; never raises."""

from __future__ import annotations

import httpx

from backend.config import Settings
from backend.schemas.analysis_schema import MainClaim, Source
from backend.services.background_service import brave_search

_MAX_QUERY_CHARS = 300


async def search_claim(client: httpx.AsyncClient, settings: Settings, claim: MainClaim) -> list[Source]:
    """Top web results for the claim text. Empty when the claim is absent, no key, or on error."""
    if not claim.found or not claim.text.strip() or not settings.brave_configured:
        return []
    query = claim.text.strip()[:_MAX_QUERY_CHARS]
    return await brave_search(client, query, settings.brave_api_key, settings.evidence_result_count)
