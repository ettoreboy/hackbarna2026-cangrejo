"""POST /api/v1/compare: two arms, shared evidence, and a survivable arm failure."""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
import respx

from backend.main import create_app
from backend.schemas.analysis_schema import AnalyzeRequest, MainClaim, Source
from backend.services.analyzer_base import AnalysisError, StepOutcome
from backend.services.background_service import BRAVE_SEARCH_URL
from backend.services.compare import _jaccard, _same_claim
from backend.services.fake_service import FakeAnalyzer
from tests.conftest import FIXTURES, WIKI_RE, _client_for, brave_ok, make_settings, wiki_ok


class BoomAnalyzer:
    """A provider that is configured but always fails, the way a dead key behaves."""

    name = "boom"
    model = "boom-1"

    async def extract_claim(self, req: AnalyzeRequest) -> StepOutcome[MainClaim]:
        raise AnalysisError("boom: model call failed")

    async def analyse(self, req, claim, evidence, background, prompt_version="v1"):
        raise AnalysisError("boom: model call failed")


def _body(fixture: str, *variants: dict) -> dict:
    return {**FIXTURES[fixture]["request"], "variants": list(variants)}


@pytest_asyncio.fixture
async def compare_client():
    app = create_app(
        settings=make_settings(BRAVE_API_KEY="brave-test"),
        analyzers={"fake": FakeAnalyzer(), "boom": BoomAnalyzer()},
    )
    async for c in _client_for(app):
        yield c


@respx.mock
async def test_two_arms_run_and_diff(compare_client):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok(("BAMF 2025", "https://bamf.example/2025", "…")))

    res = await compare_client.post(
        "/api/v1/compare",
        json=_body("spec_example", {"provider": "fake", "prompt_version": "v0"}, {"provider": "fake", "prompt_version": "v1"}),
    )
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["schema_version"] == "3"
    assert [a["label"] for a in data["arms"]] == ["fake:v0", "fake:v1"]
    assert all(a["error"] is None and a["response"] is not None for a in data["arms"])
    assert all(a["model"] == "fake-v3" for a in data["arms"])

    diff = data["diff"]
    assert set(diff["verdicts"]) == {"fake:v0", "fake:v1"}
    assert diff["verdict_agreement"] == 1.0
    assert diff["claim_agreement"] == 1.0
    assert diff["signal_overlap"] == 1.0
    assert set(diff["latency_ms"]) == {"fake:v0", "fake:v1"}
    assert data["evidence"], "top-level evidence should carry the first arm's results"


@respx.mock
async def test_claim_search_runs_once_for_both_arms(compare_client):
    """The whole point of running arms sequentially: one live Brave call, not one per arm."""
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    brave = respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok(("BAMF 2025", "https://bamf.example/2025", "…")))

    res = await compare_client.post(
        "/api/v1/compare",
        json=_body("spec_example", {"provider": "fake", "prompt_version": "v0"}, {"provider": "fake", "prompt_version": "v1"}),
    )
    assert res.status_code == 200

    claim_queries = [c.request.url.params["q"] for c in brave.calls if "background" not in c.request.url.params["q"]]
    assert len(claim_queries) == 1, f"claim search should be cached after arm 1: {claim_queries}"

    arms = res.json()["arms"]
    assert arms[0]["response"]["evidence"] == arms[1]["response"]["evidence"]


@respx.mock
async def test_one_failing_arm_does_not_fail_the_request(compare_client):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok())

    res = await compare_client.post(
        "/api/v1/compare",
        json=_body("weidel_immigration", {"provider": "boom"}, {"provider": "fake"}),
    )
    assert res.status_code == 200, res.text
    arms = {a["label"]: a for a in res.json()["arms"]}
    assert arms["boom:v1"]["error"] == "boom: model call failed"
    assert arms["boom:v1"]["response"] is None
    assert arms["fake:v1"]["response"] is not None
    # One surviving arm is not enough to compute agreement.
    assert res.json()["diff"]["verdict_agreement"] is None


@respx.mock
async def test_all_arms_failing_is_a_502(compare_client):
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    res = await compare_client.post(
        "/api/v1/compare",
        json=_body("weidel_immigration", {"provider": "boom", "prompt_version": "v0"}, {"provider": "boom", "prompt_version": "v1"}),
    )
    assert res.status_code == 502
    assert "boom" in res.json()["detail"]


async def test_unknown_provider_is_a_400(compare_client):
    res = await compare_client.post(
        "/api/v1/compare",
        json=_body("weidel_immigration", {"provider": "gemini"}, {"provider": "fake"}),
    )
    assert res.status_code == 400
    assert "gemini" in res.json()["detail"]


async def test_one_variant_is_rejected(compare_client):
    res = await compare_client.post("/api/v1/compare", json=_body("weidel_immigration", {"provider": "fake"}))
    assert res.status_code == 422


@pytest.mark.parametrize(
    "a,b,expected",
    [(set(), set(), 1.0), ({"x"}, {"x"}, 1.0), ({"x"}, {"y"}, 0.0), ({"x", "y"}, {"y", "z"}, 1 / 3)],
)
def test_jaccard(a, b, expected):
    assert _jaccard(a, b) == pytest.approx(expected)


def test_same_claim_accepts_a_longer_quote_of_the_same_span():
    """Two models picking the same sentence with different leading words still agree."""
    from backend.schemas.analysis_schema import AnalyzeResponse, ClaimCheck, PostAnalysis, SpeakerContext

    def resp(found: bool, quote: str) -> AnalyzeResponse:
        return AnalyzeResponse(
            analysis=PostAnalysis(
                main_claim=MainClaim(found=found, text="t" if found else "", quote=quote if found else ""),
                claim_check=ClaimCheck(verdict="unverifiable", explanation="", sources=[]),
                missing_context="",
                rhetorical_signals=[],
                speaker_context=SpeakerContext(name="n", role="", background="b"),
            )
        )

    assert _same_claim(resp(True, "Germany accepted 1.2M migrants"), resp(True, "accepted 1.2M migrants"))
    assert not _same_claim(resp(True, "Germany accepted 1.2M migrants"), resp(True, "inflation rose 2.2%"))
    assert not _same_claim(resp(True, "anything"), resp(False, ""))
    assert _same_claim(resp(False, ""), resp(False, ""))


@pytest.mark.asyncio
@respx.mock
async def test_compare_carries_evidence_and_author_background(compare_client):
    """Both source lists ride at the top level so the runner can show them once, not per arm."""
    respx.get(url__regex=WIKI_RE).mock(return_value=wiki_ok("Alice Weidel", "German politician, co-leader of the AfD."))
    respx.get(BRAVE_SEARCH_URL).mock(return_value=brave_ok(("BAMF 2025", "https://bamf.example/2025", "…")))
    body = _body("weidel_immigration", {"provider": "fake"}, {"provider": "fake", "prompt_version": "v0"})
    res = await compare_client.post("/api/v1/compare", json=body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert [s["url"] for s in out["evidence"]] == ["https://bamf.example/2025"]
    assert [s["provider"] for s in out["sources"]] == ["wikipedia"]
    # The top-level lists are the first successful arm's, shared by the rest via the cache.
    assert out["sources"] == out["arms"][0]["response"]["sources"]
