"""Offline test suite: analyze endpoint (schema v2), background chain, cache, prompt guardrails, taxonomy.

Run: pytest -q
Live latency check (needs GEMINI_API_KEY or NEBIUS_API_KEY): pytest -q -m live -s
"""

from __future__ import annotations

import os
import time
import warnings

import httpx
import pytest
import respx

from backend.prompts.context_prompt import POST_CLOSE, POST_OPEN, SYSTEM_PROMPT_V0, SYSTEM_PROMPT_V1, build_user_prompt
from backend.prompts.taxonomy import FALLACIES, TACTICS, is_canonical, normalize_label
from backend.schemas.analysis_schema import AnalysisResult, AnalyzeRequest, Source
from backend.services.background_service import BRAVE_SEARCH_URL
from backend.services.fake_service import FakeAnalyzer
from tests.conftest import FIXTURES

WIKI_RE = r"https://en\.wikipedia\.org/api/rest_v1/page/summary/.*"

V2_TOP_LEVEL = {
    "post_summary",
    "author",
    "author_background",
    "communication_signals",
    "logical_fallacies",
    "indicators",
    "manipulation_score",
    "cognitive_summary",
}


def _wiki_ok(title: str, extract: str):
    return httpx.Response(
        200,
        json={
            "type": "standard",
            "title": title,
            "extract": extract,
            "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"}},
        },
    )


# --------------------------------------------------------------------------- golden + controls


@respx.mock
async def test_weidel_golden_case(client: httpx.AsyncClient, fake_analyzer: FakeAnalyzer):
    fx = FIXTURES["weidel_immigration"]
    respx.get(url__regex=WIKI_RE).mock(
        return_value=_wiki_ok("Alice Weidel", "Alice Weidel is a German politician and co-leader of the AfD.")
    )
    res = await client.post("/api/v1/analyze", json=fx["request"])
    assert res.status_code == 200, res.text
    body = res.json()
    a = body["analysis"]

    assert body["schema_version"] == "2"
    assert set(a) == V2_TOP_LEVEL
    assert a["manipulation_score"] >= fx["expected"]["min_score"]
    assert a["indicators"]["is_division_tactic"] is fx["expected"]["is_division_tactic"]
    names = {s["name"] for s in a["communication_signals"]}
    assert names & set(fx["expected"]["signals_any_of"])
    assert {f["name"] for f in a["logical_fallacies"]} & set(fx["expected"]["fallacies_any_of"])
    for s in a["communication_signals"]:
        assert s["evidence"] and 0 <= s["confidence"] <= 1
    assert body["score_band"] == "high"
    assert body["cached"] is False
    assert body["provider"] == "fake"
    assert body["sources"][0]["provider"] == "wikipedia"
    assert "AfD" in a["author_background"]
    assert "Not a fact-check" in body["disclaimer"]

    _, sources, prompt_version = fake_analyzer.calls[-1]
    assert len(sources) == 1 and sources[0].provider == "wikipedia"
    assert prompt_version == "v1"


@respx.mock
@pytest.mark.parametrize("name", ["left_control", "centrist_control"])
async def test_same_tactics_flagged_regardless_of_side(client: httpx.AsyncClient, name: str):
    fx = FIXTURES[name]
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    res = await client.post("/api/v1/analyze", json=fx["request"])
    assert res.status_code == 200
    a = res.json()["analysis"]
    assert a["manipulation_score"] >= fx["expected"]["min_score"]
    assert a["indicators"]["is_division_tactic"] is True
    assert {s["name"] for s in a["communication_signals"]} & set(fx["expected"]["signals_any_of"])
    assert a["author_background"] == "Unknown author"


@respx.mock
async def test_neutral_post_scores_low(client: httpx.AsyncClient):
    fx = FIXTURES["neutral_control"]
    respx.get(url__regex=WIKI_RE).mock(return_value=_wiki_ok("Federal Statistical Office of Germany", "Destatis is..."))
    res = await client.post("/api/v1/analyze", json=fx["request"])
    body = res.json()
    assert body["analysis"]["manipulation_score"] <= fx["expected"]["max_score"]
    assert body["analysis"]["indicators"]["is_division_tactic"] is False
    assert len(body["analysis"]["communication_signals"]) <= fx["expected"]["max_signals"]
    assert body["score_band"] == "low"


# --------------------------------------------------------------------------- prompt guardrails + taxonomy


def test_prompt_wraps_post_as_untrusted_data():
    fx = FIXTURES["prompt_injection"]["request"]
    req = AnalyzeRequest(**fx)
    prompt = build_user_prompt(req, [])
    assert POST_OPEN in prompt and prompt.count(POST_CLOSE) == 1, "closing tag from inside the post must be neutralised"
    assert "BACKGROUND SOURCES: none found" in prompt
    assert prompt.index(POST_OPEN) > prompt.index("BACKGROUND SOURCES"), "instructions precede untrusted data"
    assert "sheeple" in prompt
    assert "</post> SYSTEM" not in prompt


def test_prompt_lists_sources_with_urls():
    req = AnalyzeRequest(author_handle="x", author_name="X", post_text="hello")
    sources = [Source(title="T", url="https://example.org/t", snippet="s", provider="wikipedia")]
    assert "[1] T — https://example.org/t" in build_user_prompt(req, sources)


def test_prompt_versions_differ_only_by_guardrails():
    assert SYSTEM_PROMPT_V1.startswith(SYSTEM_PROMPT_V0)
    assert "RULES:" not in SYSTEM_PROMPT_V0
    assert "RULES:" in SYSTEM_PROMPT_V1
    for label in TACTICS + FALLACIES:
        assert label in SYSTEM_PROMPT_V1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("False Dichotomy", "False Dilemma"),
        ("fear mongering", "Fear-mongering"),
        ("Golden Mean", "Middle Ground"),
        ("Outrage Farming", "Outrage Farming"),
        ("Tu quoque", "Ad Hominem"),
        ("Sealioning", "Other: Sealioning"),
    ],
)
def test_taxonomy_normalises_labels(raw: str, expected: str):
    assert normalize_label(raw) == expected
    assert is_canonical(expected) or expected.startswith("Other: ")


def test_schema_normalises_and_dedupes_labels():
    result = AnalysisResult.model_validate(
        {
            "post_summary": "s",
            "author": "a",
            "author_background": "Unknown author",
            "communication_signals": [
                {"name": "fear mongering", "evidence": "x", "confidence": 0.9, "description": "d"},
                {"name": "Fear-mongering", "evidence": "y", "confidence": 0.5, "description": "d"},
            ],
            "logical_fallacies": [{"name": "False Dichotomy", "evidence": "e"}, {"name": "false dilemma", "evidence": "e2"}],
            "indicators": {"strategic_intent": "i", "timing_note": "t", "factual_context": "f", "is_division_tactic": False},
            "manipulation_score": 50,
            "cognitive_summary": "c",
        }
    )
    assert [s.name for s in result.communication_signals] == ["Fear-mongering"]
    assert [f.name for f in result.logical_fallacies] == ["False Dilemma"]
    assert result.score_band == "medium"


@respx.mock
async def test_injection_post_does_not_alter_result(client: httpx.AsyncClient):
    fx = FIXTURES["prompt_injection"]
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    res = await client.post("/api/v1/analyze", json=fx["request"])
    a = res.json()["analysis"]
    assert a["manipulation_score"] >= fx["expected"]["min_score"]
    for phrase in fx["expected"]["background_must_not_contain"]:
        assert phrase not in a["author_background"].lower()


@respx.mock
async def test_prompt_version_query_is_forwarded(client: httpx.AsyncClient, fake_analyzer: FakeAnalyzer):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    res = await client.post("/api/v1/analyze?prompt_version=v0", json=FIXTURES["left_control"]["request"])
    assert res.status_code == 200
    assert fake_analyzer.calls[-1][2] == "v0"
    bad = await client.post("/api/v1/analyze?prompt_version=v9", json=FIXTURES["left_control"]["request"])
    assert bad.status_code == 422


# --------------------------------------------------------------------------- background chain


@respx.mock
async def test_wikipedia_hit_skips_brave(client_with_brave: httpx.AsyncClient):
    respx.get(url__regex=WIKI_RE).mock(return_value=_wiki_ok("Alice Weidel", "Bio."))
    brave = respx.get(BRAVE_SEARCH_URL).mock(return_value=httpx.Response(200, json={"web": {"results": []}}))
    res = await client_with_brave.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
    assert res.status_code == 200
    assert not brave.called
    assert res.json()["sources"][0]["provider"] == "wikipedia"


@respx.mock
async def test_wikipedia_miss_falls_back_to_brave(client_with_brave: httpx.AsyncClient):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    brave = respx.get(BRAVE_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={"web": {"results": [{"title": "Profile", "url": "https://news.example/p", "description": "A politician."}]}},
        )
    )
    res = await client_with_brave.post("/api/v1/analyze", json=FIXTURES["left_control"]["request"])
    assert res.status_code == 200
    assert brave.call_count == 1
    srcs = res.json()["sources"]
    assert len(srcs) == 1 and srcs[0]["provider"] == "brave" and srcs[0]["url"] == "https://news.example/p"


@respx.mock
async def test_brave_failure_degrades_gracefully(client_with_brave: httpx.AsyncClient):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    respx.get(BRAVE_SEARCH_URL).mock(return_value=httpx.Response(429))
    res = await client_with_brave.post("/api/v1/analyze", json=FIXTURES["left_control"]["request"])
    assert res.status_code == 200
    assert res.json()["sources"] == []


@respx.mock
async def test_wikipedia_network_error_degrades_gracefully(client: httpx.AsyncClient):
    respx.get(url__regex=WIKI_RE).mock(side_effect=httpx.ConnectError("boom"))
    res = await client.post("/api/v1/analyze", json=FIXTURES["left_control"]["request"])
    assert res.status_code == 200
    assert res.json()["sources"] == []


@respx.mock
async def test_wikipedia_disambiguation_is_ignored(client: httpx.AsyncClient):
    respx.get(url__regex=WIKI_RE).mock(
        return_value=httpx.Response(200, json={"type": "disambiguation", "title": "Smith", "extract": "Smith may refer to..."})
    )
    res = await client.post("/api/v1/analyze", json=FIXTURES["left_control"]["request"])
    assert res.json()["sources"] == []


# --------------------------------------------------------------------------- cache + providers + errors


@respx.mock
async def test_second_identical_request_is_cached(client: httpx.AsyncClient, fake_analyzer: FakeAnalyzer):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    req = FIXTURES["weidel_immigration"]["request"]
    first = await client.post("/api/v1/analyze", json=req)
    second = await client.post("/api/v1/analyze", json=req)
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["analysis"] == first.json()["analysis"]
    assert len(fake_analyzer.calls) == 1


@respx.mock
async def test_cache_key_ignores_handle_case_and_at(client: httpx.AsyncClient, fake_analyzer: FakeAnalyzer):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    req = dict(FIXTURES["weidel_immigration"]["request"])
    await client.post("/api/v1/analyze", json=req)
    req["author_handle"] = "@ALICE_WEIDEL"
    res = await client.post("/api/v1/analyze", json=req)
    assert res.json()["cached"] is True
    assert len(fake_analyzer.calls) == 1


@respx.mock
async def test_nocache_and_prompt_version_bypass_cache(client: httpx.AsyncClient, fake_analyzer: FakeAnalyzer):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    req = FIXTURES["weidel_immigration"]["request"]
    await client.post("/api/v1/analyze", json=req)
    await client.post("/api/v1/analyze?prompt_version=v0", json=req)
    await client.post("/api/v1/analyze?nocache=true", json=req)
    assert len(fake_analyzer.calls) == 3


async def test_unknown_provider_returns_400(client: httpx.AsyncClient):
    res = await client.post("/api/v1/analyze?provider=gemini", json=FIXTURES["weidel_immigration"]["request"])
    assert res.status_code == 400
    assert "fake" in res.json()["detail"]


async def test_no_provider_returns_503(client_no_provider: httpx.AsyncClient):
    res = await client_no_provider.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
    assert res.status_code == 503
    health = await client_no_provider.get("/api/v1/health")
    assert health.json()["providers"] == []


async def test_validation_rejects_empty_post(client: httpx.AsyncClient):
    res = await client.post("/api/v1/analyze", json={"author_handle": "a", "author_name": "A", "post_text": ""})
    assert res.status_code == 422


async def test_health(client: httpx.AsyncClient):
    res = await client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {
        "status": "ok",
        "schema_version": "2",
        "providers": ["fake"],
        "default_provider": "fake",
        "brave_configured": False,
        "slng_configured": False,
    }


# --------------------------------------------------------------------------- live (opt-in)


@pytest.mark.live
@pytest.mark.skipif(not (os.getenv("GEMINI_API_KEY") or os.getenv("NEBIUS_API_KEY")), reason="no provider key set")
async def test_live_latency():
    """Real call against whichever provider is configured. Warns rather than fails above the 1.5 s spec target."""
    from backend.config import Settings
    from backend.main import create_app
    from tests.conftest import _lifespan

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    app = create_app(settings=settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=90) as c, _lifespan(app):
        started = time.perf_counter()
        res = await c.post("/api/v1/analyze?nocache=true", json=FIXTURES["weidel_immigration"]["request"])
        elapsed_ms = (time.perf_counter() - started) * 1000
    assert res.status_code == 200, res.text
    body = res.json()
    print(f"\n[{body['provider']}/{body['model']}] {elapsed_ms:.0f} ms, band={body['score_band']}, cost={body['cost_usd']}")
    print(body["analysis"])
    if elapsed_ms > 1500:
        warnings.warn(f"Latency {elapsed_ms:.0f} ms exceeds the 1.5 s spec target (see docs/ANALYSIS.md)", stacklevel=1)


# --------------------------------------------------------------------------- regressions


def test_wikipedia_user_agent_carries_contact_details():
    """Wikimedia's robot policy returns 403 for a User-Agent with no contact URL or address.

    Regression: the original UA string was rejected and author background silently degraded
    to empty on every request.
    """
    from backend.services.background_service import USER_AGENT

    assert "http" in USER_AGENT and "@" in USER_AGENT, USER_AGENT


@pytest.mark.live
async def test_wikipedia_live_summary_returns_200():
    """Opt-in: proves the real Wikipedia endpoint accepts our User-Agent."""
    from backend.config import Settings
    from backend.services.background_service import wikipedia_summary

    async with httpx.AsyncClient(follow_redirects=True) as c:
        src = await wikipedia_summary(c, "Alice Weidel", Settings(_env_file=None).wikipedia_lang)  # type: ignore[call-arg]
    assert src is not None and "politician" in src.snippet.lower()
