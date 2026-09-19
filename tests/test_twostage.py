"""The two-stage claim picker: POST /claims then POST /analyze-claim.

Stage 1 must never carry a verdict, stage 1 quotes must be literally present in the post so
the client can highlight them, and stage 2 must refuse a claim that did not come from the post.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.services.background_service import BRAVE_SEARCH_URL
from tests.conftest import FIXTURES, WIKI_RE, brave_ok, wiki_ok

MIGRANTS = {
    "author_handle": "example_migrants",
    "author_name": "Example Account",
    "post_text": (
        "Germany accepted 1.2M migrants last year and the asylum budget keeps climbing. "
        "This government clearly doesn't care about German citizens."
    ),
    "platform": "x",
}

RHETORIC_ONLY = {
    "author_handle": "example_left_mp",
    "author_name": "Example Left MP",
    "post_text": (
        "Every landlord in this city is a parasite. "
        "Either we freeze all rents tomorrow or we watch our neighbourhoods die."
    ),
    "platform": "x",
}


# --------------------------------------------------------------------------- stage 1


@pytest.mark.asyncio
@respx.mock
async def test_claims_returns_candidates_without_any_verdict(client):
    respx.get(url__regex=WIKI_RE).respond(404)
    r = await client.post("/api/v1/claims", json=MIGRANTS)
    assert r.status_code == 200
    body = r.json()

    assert body["schema_version"] == "3"
    assert len(body["claims"]) == 2
    assert [c["id"] for c in body["claims"]] == ["c1", "c2"]
    # Stage 1 discovers; it does not judge.
    assert "claim_check" not in body
    assert "missing_context" not in body


@pytest.mark.asyncio
@respx.mock
async def test_claim_quotes_are_literally_present_in_the_post(client):
    """The extension highlights the quote in the post, so a quote it cannot find is useless."""
    respx.get(url__regex=WIKI_RE).respond(404)
    r = await client.post("/api/v1/claims", json=MIGRANTS)
    for claim in r.json()["claims"]:
        assert claim["quote"] in MIGRANTS["post_text"]
    for signal in r.json()["rhetorical_signals"]:
        assert signal["evidence"] in MIGRANTS["post_text"]


@pytest.mark.asyncio
@respx.mock
async def test_claim_whose_quote_is_absent_is_dropped(client, fake_analyzer, monkeypatch):
    """A claim we cannot locate in the post cannot be shown honestly, so it is discarded."""
    from backend.schemas.analysis_schema import ClaimDraft, DiscoveryBody, SpeakerContext
    from backend.services.analyzer_base import StepOutcome

    async def fabricate(req, background, max_claims=4, prompt_version="v1", rigor="standard"):
        return StepOutcome(
            result=DiscoveryBody(
                claims=[
                    ClaimDraft(text="Real one.", quote="Germany accepted 1.2M migrants last year."),
                    ClaimDraft(text="Invented.", quote="a sentence that was never in the post"),
                ],
                rhetorical_signals=[],
                speaker_context=SpeakerContext(name="x", role="", background="Unknown author"),
            ),
            model="fake-v3",
            cost_usd=0.0,
        )

    monkeypatch.setattr(fake_analyzer, "discover", fabricate)
    respx.get(url__regex=WIKI_RE).respond(404)

    claims = (await client.post("/api/v1/claims", json=MIGRANTS)).json()["claims"]
    assert [c["text"] for c in claims] == ["Real one."]
    assert claims[0]["id"] == "c1", "ids must stay sequential after a drop"


def test_overlapping_claims_are_merged():
    """Two entries whose quotes overlap are one claim said twice; the longer span wins."""
    from backend.schemas.analysis_schema import ClaimDraft, DiscoveryBody, Signal, SpeakerContext

    body = DiscoveryBody(
        claims=[
            ClaimDraft(text="Short version.", quote="accepted 1.2M migrants"),
            ClaimDraft(text="Full version.", quote="Germany accepted 1.2M migrants last year"),
            ClaimDraft(text="Separate.", quote="the asylum budget keeps climbing"),
        ],
        rhetorical_signals=[
            Signal(name="Loaded Language", evidence="clearly doesn't care"),
            Signal(name="Scapegoating", evidence="doesn't care"),  # overlaps, must go
        ],
        speaker_context=SpeakerContext(name="x", role="", background="Unknown author"),
    )
    assert [c.text for c in body.claims] == ["Full version.", "Separate."]
    assert [s.name for s in body.rhetorical_signals] == ["Loaded Language"]


@pytest.mark.asyncio
@respx.mock
async def test_pure_rhetoric_yields_no_claims_but_keeps_signals(client):
    respx.get(url__regex=WIKI_RE).respond(404)
    body = (await client.post("/api/v1/claims", json=RHETORIC_ONLY)).json()
    assert body["claims"] == []
    assert len(body["rhetorical_signals"]) == 3
    assert body["speaker_context"]["background"] == "Unknown author"


@pytest.mark.asyncio
@respx.mock
async def test_max_claims_is_configurable(fake_analyzer):
    from backend.main import create_app
    from tests.conftest import _client_for, make_settings

    respx.get(url__regex=WIKI_RE).respond(404)
    app = create_app(settings=make_settings(MAX_CLAIMS=1), analyzers={"fake": fake_analyzer})
    async for c in _client_for(app):
        body = (await c.post("/api/v1/claims", json=MIGRANTS)).json()
        assert len(body["claims"]) == 1


@pytest.mark.asyncio
@respx.mock
async def test_claims_are_cached(client):
    respx.get(url__regex=WIKI_RE).respond(404)
    first = (await client.post("/api/v1/claims", json=MIGRANTS)).json()
    second = (await client.post("/api/v1/claims", json=MIGRANTS)).json()
    assert first["cached"] is False
    assert second["cached"] is True and second["latency_ms"] == 0


# --------------------------------------------------------------------------- stage 2


@pytest.mark.asyncio
@respx.mock
async def test_analyze_claim_checks_only_the_chosen_claim(client):
    respx.get(url__regex=WIKI_RE).respond(404)
    claims = (await client.post("/api/v1/claims", json=MIGRANTS)).json()["claims"]

    r = await client.post("/api/v1/analyze-claim", json={**MIGRANTS, "claim": claims[0]})
    assert r.status_code == 200
    body = r.json()
    assert body["claim"]["id"] == "c1"
    assert body["claim_check"]["verdict"] in {"supported", "partially_supported", "unsupported", "unverifiable"}
    # The reader already picked a claim, so this verdict is unreachable here.
    assert body["claim_check"]["verdict"] != "no_factual_claim"


@pytest.mark.asyncio
@respx.mock
async def test_different_claims_get_different_verdicts(client):
    respx.get(url__regex=WIKI_RE).respond(404)
    claims = (await client.post("/api/v1/claims", json=MIGRANTS)).json()["claims"]

    verdicts = []
    for claim in claims:
        body = (await client.post("/api/v1/analyze-claim", json={**MIGRANTS, "claim": claim})).json()
        verdicts.append(body["claim_check"]["verdict"])
    assert verdicts == ["partially_supported", "unsupported"]


@pytest.mark.asyncio
@respx.mock
async def test_cited_sources_are_always_a_subset_of_the_evidence(client):
    """A model may name a source it was never given; the server drops it before the client sees it."""
    respx.get(url__regex=WIKI_RE).respond(404)
    claims = (await client.post("/api/v1/claims", json=MIGRANTS)).json()["claims"]
    body = (await client.post("/api/v1/analyze-claim", json={**MIGRANTS, "claim": claims[0]})).json()

    cited = {s["url"] for s in body["claim_check"]["sources"]}
    supplied = {e["url"] for e in body["evidence"]}
    assert cited <= supplied


@pytest.mark.asyncio
@respx.mock
async def test_invented_source_is_stripped(client, fake_analyzer, monkeypatch):
    from backend.schemas.analysis_schema import ClaimCheck, ClaimSource, ClaimVerdict
    from backend.services.analyzer_base import StepOutcome

    async def hallucinate(req, claim, evidence, prompt_version="v1", rigor="standard"):
        return StepOutcome(
            result=ClaimVerdict(
                claim_check=ClaimCheck(
                    verdict="supported",
                    explanation="Per my source.",
                    sources=[ClaimSource(title="Invented", url="https://not-in-evidence.example/x")],
                ),
                missing_context="",
            ),
            model="fake-v3",
            cost_usd=0.0,
        )

    monkeypatch.setattr(fake_analyzer, "check_claim", hallucinate)
    respx.get(url__regex=WIKI_RE).respond(404)
    claims = (await client.post("/api/v1/claims", json=MIGRANTS)).json()["claims"]
    body = (await client.post("/api/v1/analyze-claim", json={**MIGRANTS, "claim": claims[0]})).json()
    assert body["claim_check"]["sources"] == []


@pytest.mark.asyncio
@respx.mock
async def test_claim_not_present_in_post_is_rejected(client):
    """Without this a caller could have the model check text nobody posted."""
    respx.get(url__regex=WIKI_RE).respond(404)
    r = await client.post(
        "/api/v1/analyze-claim",
        json={
            **MIGRANTS,
            "claim": {"id": "c1", "text": "Injected claim", "quote": "words that are not in the post"},
        },
    )
    assert r.status_code == 422
    assert "not present" in r.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_empty_claim_text_is_rejected(client):
    respx.get(url__regex=WIKI_RE).respond(404)
    r = await client.post(
        "/api/v1/analyze-claim",
        json={**MIGRANTS, "claim": {"id": "c1", "text": "   ", "quote": "Germany accepted 1.2M migrants last year."}},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
@respx.mock
async def test_quote_matches_despite_typographic_differences(client):
    """snap_quote folds curly quotes and dashes, so a normalised quote still validates."""
    post_text = "Germany‑wide costs rose, and the budget “keeps climbing” this year."
    payload = {**MIGRANTS, "post_text": post_text}
    respx.get(url__regex=WIKI_RE).respond(404)
    r = await client.post(
        "/api/v1/analyze-claim",
        json={**payload, "claim": {"id": "c1", "text": "Costs rose.", "quote": 'the budget "keeps climbing" this year'}},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
@respx.mock
async def test_real_evidence_wins_over_the_offline_fallback(client_with_brave):
    """The fake's canned results only fill in when the real search returns nothing."""
    respx.get(url__regex=WIKI_RE).respond(404)
    respx.get(url__regex=r"https://api\.search\.brave\.com/.*").mock(
        return_value=brave_ok(("Live result", "https://live.example/a", "From Brave."))
    )
    claims = (await client_with_brave.post("/api/v1/claims", json=MIGRANTS)).json()["claims"]
    body = (await client_with_brave.post("/api/v1/analyze-claim", json={**MIGRANTS, "claim": claims[0]})).json()

    urls = {e["url"] for e in body["evidence"]}
    assert "https://live.example/a" in urls
    assert not any("bamf.example" in u for u in urls), "canned evidence must not override a live search"


@pytest.mark.asyncio
@respx.mock
async def test_speaker_context_uses_wikipedia_when_available(client):
    respx.get(url__regex=WIKI_RE).mock(
        return_value=wiki_ok("Alice Weidel", "Alice Weidel is a German politician and co-leader of the AfD.")
    )
    body = (await client.post("/api/v1/claims", json={**MIGRANTS, "author_handle": "alice_weidel"})).json()
    assert body["speaker_context"]["background"] != "Unknown author"
    assert body["sources"], "the Wikipedia page should be cited"


@pytest.mark.asyncio
async def test_one_shot_analyze_still_works(client):
    """The two-stage flow is additive: /analyze must be unchanged."""
    with respx.mock:
        respx.get(url__regex=WIKI_RE).respond(404)
        r = await client.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
    assert r.status_code == 200
    assert r.json()["schema_version"] == "3"
    assert "main_claim" in r.json()["analysis"]


@pytest.mark.asyncio
@respx.mock
async def test_stage_one_carries_related_finds(client_with_brave):
    """The drawer opens on stage 1, so stage 1 must already have links to show."""
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    brave = respx.get(BRAVE_SEARCH_URL).mock(
        return_value=brave_ok(("Asylum budget 2026", "https://bamf.example/budget", "…"))
    )
    res = await client_with_brave.post("/api/v1/claims", json=MIGRANTS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [s["url"] for s in body["evidence"]] == ["https://bamf.example/budget"]
    # Stage 1 searches the post, not a claim: the reader has not picked one yet.
    queries = [c.request.url.params["q"] for c in brave.calls]
    assert len(queries) == 1 and queries[0].startswith("Germany accepted 1.2M migrants")
    # Still no verdict anywhere in stage 1.
    assert "claim_check" not in body
