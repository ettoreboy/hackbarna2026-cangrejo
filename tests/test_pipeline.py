"""Basic tests for the claim-first pipeline on the fake provider. Run: pytest -q"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.prompts.claim_prompt import build_claim_prompt
from backend.prompts.context_prompt import SYSTEM_PROMPT_V0, SYSTEM_PROMPT_V1, build_user_prompt
from backend.prompts.taxonomy import normalize_label
from backend.schemas.analysis_schema import AnalyzeRequest, MainClaim
from backend.services.background_service import BRAVE_SEARCH_URL
from tests.conftest import FIXTURES, WIKI_RE, brave_ok, wiki_ok

V3_BLOCKS = {"main_claim", "claim_check", "missing_context", "rhetorical_signals", "speaker_context"}


@respx.mock
async def test_spec_example_extracts_the_factual_sentence_only(client_with_brave):
    """The user's example: sentence 1 is the claim, sentence 2 is only a rhetorical signal."""
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok(("BAMF 2025 report", "https://bamf.example/2025", "…")))
    fx = FIXTURES["spec_example"]
    res = await client_with_brave.post("/api/v1/analyze", json=fx["request"])
    assert res.status_code == 200, res.text
    a = res.json()["analysis"]
    assert set(a) == V3_BLOCKS
    assert a["main_claim"]["found"] is True
    assert a["main_claim"]["quote"] == fx["expected"]["claim_quote"]
    assert "clearly doesn't care" not in a["main_claim"]["text"]
    assert any("clearly doesn't care" in s["evidence"] for s in a["rhetorical_signals"])
    assert a["claim_check"]["verdict"] == "partially_supported"
    assert a["claim_check"]["sources"] == [{"title": "BAMF 2025 report", "url": "https://bamf.example/2025"}]


@respx.mock
async def test_no_factual_claim_skips_search_and_sets_verdict(client_with_brave, fake_analyzer):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    brave = respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok())
    res = await client_with_brave.post("/api/v1/analyze", json=FIXTURES["left_control"]["request"])
    a = res.json()["analysis"]
    assert a["main_claim"]["found"] is False
    assert a["claim_check"]["verdict"] == "no_factual_claim"
    assert a["claim_check"]["sources"] == []
    assert res.json()["evidence"] == []
    # Brave is still used for author background; it must not be used to search a claim.
    queries = [c.request.url.params["q"] for c in brave.calls]
    assert all("background" in q for q in queries), f"claim search should not run: {queries}"


@respx.mock
async def test_no_evidence_means_unverifiable(client):
    """No Brave key configured: verdict cannot be stronger than unverifiable."""
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    res = await client.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
    assert res.json()["analysis"]["claim_check"]["verdict"] == "unverifiable"


@respx.mock
async def test_speaker_background_comes_from_wikipedia_or_is_unknown(client):
    respx.get(url__regex=WIKI_RE).mock(return_value=wiki_ok("Alice Weidel", "Alice Weidel is a German politician and co-leader of the AfD."))
    res = await client.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
    sp = res.json()["analysis"]["speaker_context"]
    assert "AfD" in sp["background"] and sp["role"] == "Politician"
    assert res.json()["sources"][0]["provider"] == "wikipedia"

    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    res = await client.post("/api/v1/analyze?nocache=true", json=FIXTURES["prompt_injection"]["request"])
    sp = res.json()["analysis"]["speaker_context"]
    assert sp["background"] == "Unknown author"
    assert "trusted expert" not in sp["background"].lower()


@respx.mock
async def test_neutral_post_has_no_signals(client):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    res = await client.post("/api/v1/analyze", json=FIXTURES["neutral_control"]["request"])
    assert res.json()["analysis"]["rhetorical_signals"] == []


@respx.mock
async def test_cache_and_timings(client, fake_analyzer):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    req = FIXTURES["weidel_immigration"]["request"]
    first = await client.post("/api/v1/analyze", json=req)
    second = await client.post("/api/v1/analyze", json=req)
    assert first.json()["cached"] is False and second.json()["cached"] is True
    assert len(fake_analyzer.analyse_calls) == 1
    assert set(first.json()["steps"]) == {"extract_ms", "evidence_ms", "analyse_ms"}
    assert first.json()["schema_version"] == "3"


async def test_no_provider_returns_503(client_no_provider):
    res = await client_no_provider.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
    assert res.status_code == 503
    assert (await client_no_provider.get("/api/v1/health")).json()["providers"] == []


def test_prompts_wrap_post_and_v0_has_no_rules():
    req = AnalyzeRequest(**FIXTURES["prompt_injection"]["request"])
    claim_prompt = build_claim_prompt(req)
    assert claim_prompt.count("</post>") == 1, "closing tag inside the post must be neutralised"
    user = build_user_prompt(req, MainClaim(found=False, text="", quote=""), [], [])
    assert "none found" in user and user.count("</post>") == 1
    assert "RULES:" in SYSTEM_PROMPT_V1 and "RULES:" not in SYSTEM_PROMPT_V0
    for verdict in ("supported", "partially_supported", "unsupported", "unverifiable", "no_factual_claim"):
        assert f'"{verdict}"' in SYSTEM_PROMPT_V0, "every verdict value is defined in the prompt text"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Fear‑mongering", "Fear-mongering"),  # U+2011, as returned by gpt-oss live
        ("fear appeal", "Fear-mongering"),
        ("Us vs. them", "Us-vs-Them Framing"),
        ("loaded words", "Loaded Language"),
        ("False Dichotomy", "False Dilemma"),
        ("Sealioning", "Other: Sealioning"),
    ],
)
def test_taxonomy_normalises_labels(raw, expected):
    assert normalize_label(raw) == expected
