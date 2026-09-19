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
async def test_no_factual_claim_still_returns_related_finds(client_with_brave, fake_analyzer):
    """A post with nothing checkable gets no verdict and no citations, but still gets links."""
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    brave = respx.get(BRAVE_SEARCH_URL).mock(
        return_value=brave_ok(("Rent control evidence review", "https://econ.example/rent-control", "…"))
    )
    res = await client_with_brave.post("/api/v1/analyze", json=FIXTURES["left_control"]["request"])
    a = res.json()["analysis"]
    assert a["main_claim"]["found"] is False
    assert a["claim_check"]["verdict"] == "no_factual_claim"
    # The verdict rests on nothing, so it cites nothing.
    assert a["claim_check"]["sources"] == []
    # The reader still gets somewhere to go next.
    assert [s["url"] for s in res.json()["evidence"]] == ["https://econ.example/rent-control"]
    # One query, and it is the post itself: there is no claim to search for.
    queries = [c.request.url.params["q"] for c in brave.calls]
    assert len(queries) == 1, f"expected only the post-text search: {queries}"
    assert queries[0].startswith("Every landlord in this city")


@respx.mock
async def test_no_evidence_means_unverifiable(client):
    """No Brave key and no canned results for this author: cannot be stronger than unverifiable."""
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    req = dict(FIXTURES["weidel_immigration"]["request"], author_handle="unknown_backbencher")
    res = await client.post("/api/v1/analyze", json=req)
    assert res.json()["evidence"] == []
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


# --------------------------------------------------------------------------- brave cache + budget


@respx.mock
async def test_brave_cache_hit_skips_the_network_and_budget_stops_live_calls():
    import httpx as _httpx

    from backend.schemas.analysis_schema import MainClaim as _Claim
    from backend.services.evidence_service import search_claim
    from backend.services.search_cache import NullCache
    from tests.conftest import make_settings

    cache = NullCache()
    settings = make_settings(BRAVE_API_KEY="brave-test", BRAVE_BUDGET=1)
    brave = respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok(("T", "https://e.example/1", "snippet")))
    claim = _Claim(found=True, text="Germany accepted 1.2 million migrants last year.", quote="x")

    async with _httpx.AsyncClient() as http:
        first = await search_claim(http, settings, claim, cache)
        second = await search_claim(http, settings, claim, cache)  # same claim, different spacing/case
        second_again = await search_claim(http, settings, _Claim(found=True, text="  germany accepted 1.2 MILLION migrants last year. ", quote="x"), cache)
        other = await search_claim(http, settings, _Claim(found=True, text="A different claim.", quote="x"), cache)

    assert first and second == first and second_again == first
    assert brave.call_count == 1, "cache hit must not touch the network"
    assert cache.live_calls() == 1
    assert other == [], "budget of 1 live call reached: degrade to no evidence"


# --------------------------------------------------------------------------- always-on resources
#
# The contract the extension relies on: every analysis surface hands the reader something to
# click. The claim search wins when it finds anything; otherwise the post itself is searched;
# canned results are the last resort so fake mode still demos.


def test_post_query_drops_links_handles_and_hashes():
    from backend.services.evidence_service import query_from_post

    q = query_from_post("Hey @alice_weidel, #migration is out of control https://t.co/abc123 www.x.example/y")
    assert q == "Hey , migration is out of control"
    assert query_from_post("https://t.co/onlyalink") == "", "a link-only post has nothing to search for"
    assert len(query_from_post("word " * 200)) <= 300


@respx.mock
async def test_claim_search_wins_and_the_post_search_does_not_run(client_with_brave):
    """The fallback is a fallback: one live call when the claim search already returned results."""
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    brave = respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok(("BAMF 2025", "https://bamf.example/2025", "…")))
    res = await client_with_brave.post("/api/v1/analyze", json=FIXTURES["spec_example"]["request"])
    assert [s["url"] for s in res.json()["evidence"]] == ["https://bamf.example/2025"]
    queries = [c.request.url.params["q"] for c in brave.calls]
    assert len(queries) == 1, f"post search should not run: {queries}"
    assert queries[0].startswith("Germany accepted 1.2 million migrants")


@respx.mock
async def test_fake_mode_analyze_has_evidence_without_a_brave_key(client):
    """The demo runs with no keys at all: canned results reach /analyze, not just /analyze-claim."""
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    res = await client.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
    evidence = res.json()["evidence"]
    assert evidence, "fake mode must not show an empty resources panel"
    assert evidence[0]["url"] == "https://www.bamf.example/irregular-migration-2026"
    assert res.json()["analysis"]["claim_check"]["verdict"] != "unverifiable"


@respx.mock
async def test_the_post_fallback_respects_the_brave_budget():
    """Over budget is not an error: the fallback degrades to no evidence, network untouched."""
    from backend.services.evidence_service import gather_evidence
    from backend.services.search_cache import NullCache
    from tests.conftest import make_settings

    settings = make_settings(BRAVE_API_KEY="brave-test", BRAVE_BUDGET=0)
    brave = respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok(("T", "https://e.example/1", "s")))
    claim = MainClaim(found=True, text="Germany accepted 1.2 million migrants last year.", quote="x")

    async with httpx.AsyncClient() as http:
        found = await gather_evidence(http, settings, claim, "Germany accepted 1.2M migrants.", NullCache())

    assert found == []
    assert brave.call_count == 0, "neither the claim search nor the post fallback may exceed the budget"
