"""Nebius Token Factory provider: strict schema, fallback, salvage, cost, error mapping.

The model endpoint is driven through a mock transport (tests/nebius_mock.py) because the
openai SDK uses its own vendored HTTP stack; Wikipedia and Brave are still mocked with respx.
No API key is needed for any test here.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from backend.config import Settings
from backend.main import create_app
from backend.schemas.analysis_schema import AnalysisResult, AnalyzeRequest
from backend.services.analyzer_base import AnalysisError
from backend.services.nebius_service import NebiusAnalyzer, _extract_json_object
from backend.services.pricing import cost_usd
from backend.services.schema_tools import response_format_strict, to_strict_schema
from tests.conftest import FIXTURES, _lifespan
from tests.nebius_mock import MockChatServer, api_error, chat_completion

WIKI_RE = r"https://en\.wikipedia\.org/api/rest_v1/page/summary/.*"

VALID_ANALYSIS = {
    "post_summary": "The author blames one group for a broad economic problem.",
    "author": "Alice Weidel",
    "author_background": "Co-leader of the AfD, a German far-right party.",
    "communication_signals": [
        {"name": "Scapegoating", "evidence": "illegal migrants", "confidence": 0.9, "description": "Single cause named."},
        {"name": "False Dichotomy", "evidence": "Either we", "confidence": 0.8, "description": "Two options only."},
    ],
    "logical_fallacies": [{"name": "False Dichotomy", "evidence": "Either we close the borders now"}],
    "indicators": {
        "strategic_intent": "Mobilise the base.",
        "timing_note": "No timing signal identified.",
        "factual_context": "The causal claim is unsupported.",
        "is_division_tactic": True,
    },
    "manipulation_score": 85,
    "cognitive_summary": "Culprit plus binary choice is a mobilisation pattern.",
}


def settings(**over) -> Settings:
    base = {
        "ANALYZER_PROVIDER": "nebius",
        "NEBIUS_API_KEY": "test-key",
        "NEBIUS_MODEL": "Qwen/Qwen3-32B",
        "GEMINI_API_KEY": "",
        "BRAVE_API_KEY": "",
    }
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def analyzer_with(server: MockChatServer, **over) -> NebiusAnalyzer:
    return NebiusAnalyzer(settings(**over), client=server.client())


def request_of(name: str = "weidel_immigration") -> AnalyzeRequest:
    return AnalyzeRequest(**FIXTURES[name]["request"])


# --------------------------------------------------------------------------- schema sanitiser


def test_strict_schema_is_accepted_shape():
    strict = to_strict_schema(AnalysisResult.model_json_schema())

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"]), node.get("title")
            for banned in ("minimum", "maximum", "maxLength", "pattern", "format", "default"):
                assert banned not in node, f"{banned} survived sanitisation"
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    check(strict)
    assert set(strict["properties"]) == set(AnalysisResult.model_json_schema()["properties"])
    assert "$defs" in strict


def test_strict_schema_does_not_mutate_the_original():
    original = AnalysisResult.model_json_schema()
    before = json.dumps(original, sort_keys=True)
    to_strict_schema(original)
    assert json.dumps(original, sort_keys=True) == before


def test_response_format_uses_the_wrapped_form():
    rf = response_format_strict("context_guard_analysis", AnalysisResult.model_json_schema())
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "context_guard_analysis"
    assert rf["json_schema"]["strict"] is True
    assert "properties" in rf["json_schema"]["schema"]


# --------------------------------------------------------------------------- happy path


async def test_strict_request_shape_and_parsing():
    server = MockChatServer(chat_completion(VALID_ANALYSIS))
    outcome = await analyzer_with(server).analyze(request_of(), [])

    sent = server.body()
    assert sent["model"] == "Qwen/Qwen3-32B"
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["temperature"] == 0.2
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert "<post>" in sent["messages"][1]["content"]
    assert "Outrage Farming" in sent["messages"][0]["content"], "v1 prompt carries the taxonomy"

    assert outcome.result.manipulation_score == 85
    assert outcome.result.score_band == "high"
    # Synonym normalisation still applies to model output.
    assert [s.name for s in outcome.result.communication_signals] == ["Scapegoating", "False Dilemma"]
    assert [f.name for f in outcome.result.logical_fallacies] == ["False Dilemma"]
    assert outcome.model == "Qwen/Qwen3-32B"
    assert outcome.prompt_tokens == 1200 and outcome.completion_tokens == 300


async def test_prompt_version_v0_omits_guardrails():
    server = MockChatServer(chat_completion(VALID_ANALYSIS))
    await analyzer_with(server).analyze(request_of(), [], prompt_version="v0")
    system = server.body()["messages"][0]["content"]
    assert "RULES:" not in system
    assert "ALLOWED communication_signals" not in system


async def test_sources_reach_the_prompt():
    from backend.schemas.analysis_schema import Source

    server = MockChatServer(chat_completion(VALID_ANALYSIS))
    src = Source(title="Alice Weidel", url="https://en.wikipedia.org/wiki/Alice_Weidel", snippet="Co-leader of the AfD.", provider="wikipedia")
    await analyzer_with(server).analyze(request_of(), [src])
    user = server.body()["messages"][1]["content"]
    assert "[1] Alice Weidel — https://en.wikipedia.org/wiki/Alice_Weidel" in user


# --------------------------------------------------------------------------- strict-mode fallback


async def test_falls_back_to_json_object_when_strict_is_rejected():
    server = MockChatServer(
        api_error(400, "response_format json_schema is not supported for this model"),
        chat_completion(VALID_ANALYSIS),
    )
    analyzer = analyzer_with(server)
    outcome = await analyzer.analyze(request_of(), [])

    assert outcome.result.manipulation_score == 85
    assert server.call_count == 2
    retry = server.body(1)
    assert retry["response_format"] == {"type": "json_object"}
    assert "exactly these keys" in retry["messages"][0]["content"], "schema restated in the prompt"
    assert analyzer._use_strict is False


async def test_fallback_is_remembered_so_it_costs_one_retry_only():
    server = MockChatServer(
        api_error(400, "unsupported response_format: json_schema"),
        chat_completion(VALID_ANALYSIS),
    )
    analyzer = analyzer_with(server)
    await analyzer.analyze(request_of(), [])
    await analyzer.analyze(request_of(), [])
    assert server.call_count == 3, "second analyze must not retry strict mode again"
    assert server.body(2)["response_format"] == {"type": "json_object"}


async def test_unrelated_400_is_not_treated_as_a_strict_mode_problem():
    server = MockChatServer(api_error(400, "max_tokens must be a positive integer"))
    with pytest.raises(AnalysisError, match="Nebius call failed"):
        await analyzer_with(server).analyze(request_of(), [])
    assert server.call_count == 1, "no fallback retry for an unrelated error"


# --------------------------------------------------------------------------- resilience


async def test_salvages_json_wrapped_in_a_fenced_block():
    fenced = "Here is the analysis:\n```json\n" + json.dumps(VALID_ANALYSIS) + "\n```\nHope that helps."
    server = MockChatServer(chat_completion(fenced))
    outcome = await analyzer_with(server).analyze(request_of(), [])
    assert outcome.result.manipulation_score == 85


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('prose {"a": {"b": 2}} more', {"a": {"b": 2}}),
        ('```json\n{"a": "brace } inside string"}\n```', {"a": "brace } inside string"}),
        ('{"a": "escaped \\" quote"}', {"a": 'escaped " quote'}),
        ("no json here", None),
        ('{"unbalanced": ', None),
    ],
)
def test_json_object_extractor(text, expected):
    assert _extract_json_object(text) == expected


async def test_truncated_response_is_an_error_not_a_silent_partial():
    server = MockChatServer(chat_completion('{"post_summary": "cut off', finish_reason="length"))
    with pytest.raises(AnalysisError, match="token limit"):
        await analyzer_with(server).analyze(request_of(), [])


async def test_empty_content_is_an_error():
    server = MockChatServer(chat_completion("", finish_reason="content_filter"))
    with pytest.raises(AnalysisError, match="empty content"):
        await analyzer_with(server).analyze(request_of(), [])


async def test_schema_mismatch_is_an_error():
    server = MockChatServer(chat_completion({"post_summary": "only this field"}))
    with pytest.raises(AnalysisError, match="does not match the schema"):
        await analyzer_with(server).analyze(request_of(), [])


async def test_upstream_500_is_surfaced():
    server = MockChatServer(api_error(500, "internal"))
    with pytest.raises(AnalysisError, match="Nebius call failed"):
        await analyzer_with(server).analyze(request_of(), [])


def test_missing_key_refuses_to_construct():
    with pytest.raises(AnalysisError, match="NEBIUS_API_KEY"):
        NebiusAnalyzer(settings(NEBIUS_API_KEY=""))


# --------------------------------------------------------------------------- pricing


def test_cost_is_computed_for_a_known_model():
    # 1M in + 1M out at (0.10, 0.30) = 0.40
    assert cost_usd("nebius", "Qwen/Qwen3-32B", 1_000_000, 1_000_000) == pytest.approx(0.40)


def test_cost_is_none_for_an_unknown_model():
    assert cost_usd("nebius", "some/unlisted-model", 1000, 1000) is None


def test_price_overrides_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("NEBIUS_PRICES", '{"some/unlisted-model": [1.0, 2.0]}')
    assert cost_usd("nebius", "some/unlisted-model", 1_000_000, 1_000_000) == pytest.approx(3.0)


def test_malformed_price_override_is_ignored(monkeypatch):
    monkeypatch.setenv("NEBIUS_PRICES", "not json")
    assert cost_usd("nebius", "Qwen/Qwen3-32B", 1_000_000, 0) == pytest.approx(0.10)


async def test_outcome_carries_cost():
    server = MockChatServer(chat_completion(VALID_ANALYSIS, prompt_tokens=1_000_000, completion_tokens=0))
    outcome = await analyzer_with(server).analyze(request_of(), [])
    assert outcome.cost_usd == pytest.approx(0.10)


# --------------------------------------------------------------------------- wired into the app


@respx.mock
async def test_endpoint_uses_nebius_and_reports_provider_and_cost():
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    server = MockChatServer(chat_completion(VALID_ANALYSIS))
    app = create_app(settings=settings(), analyzers={"nebius": analyzer_with(server)})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c, _lifespan(app):
        res = await c.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
        health = await c.get("/api/v1/health")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider"] == "nebius"
    assert body["model"] == "Qwen/Qwen3-32B"
    assert body["cost_usd"] == pytest.approx((1200 * 0.10 + 300 * 0.30) / 1_000_000)
    assert body["analysis"]["post_summary"].startswith("The author blames")
    assert health.json()["providers"] == ["nebius"]
    assert health.json()["default_provider"] == "nebius"


@respx.mock
async def test_upstream_failure_maps_to_502():
    respx.get(url__regex=WIKI_RE).mock(return_value=httpx.Response(404))
    server = MockChatServer(api_error(503, "overloaded"))
    app = create_app(settings=settings(), analyzers={"nebius": analyzer_with(server)})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c, _lifespan(app):
        res = await c.post("/api/v1/analyze", json=FIXTURES["weidel_immigration"]["request"])
    assert res.status_code == 502
    assert "Nebius" in res.json()["detail"]


async def test_build_analyzers_registers_nebius_from_settings():
    """The real registry path: a configured key produces a working nebius provider."""
    from backend.main import build_analyzers

    analyzers = build_analyzers(settings(GEMINI_API_KEY=""))
    assert set(analyzers) == {"nebius"}
    assert analyzers["nebius"].model == "Qwen/Qwen3-32B"


async def test_build_analyzers_registers_both_when_both_keys_present():
    from backend.main import build_analyzers

    analyzers = build_analyzers(settings(GEMINI_API_KEY="g-test"))
    assert set(analyzers) == {"nebius", "gemini"}


# --------------------------------------------------------------------------- live (opt-in)


@pytest.mark.live
@pytest.mark.skipif(not __import__("os").getenv("NEBIUS_API_KEY"), reason="NEBIUS_API_KEY not set")
async def test_live_nebius_structured_output():
    """One real call. Proves strict json_schema works on the configured model."""
    import time

    from backend.schemas.analysis_schema import Source

    s = Settings(_env_file=None, ANALYZER_PROVIDER="nebius")  # type: ignore[call-arg]
    analyzer = NebiusAnalyzer(s)
    src = Source(
        title="Alice Weidel",
        url="https://en.wikipedia.org/wiki/Alice_Weidel",
        snippet="Alice Weidel is a German politician and co-leader of the AfD.",
        provider="wikipedia",
    )
    started = time.perf_counter()
    outcome = await analyzer.analyze(request_of(), [src])
    elapsed_ms = (time.perf_counter() - started) * 1000

    mode = "strict" if analyzer._use_strict else "json_object fallback"
    print(f"\n[{s.nebius_model}] {elapsed_ms:.0f} ms via {mode}, cost={outcome.cost_usd}")
    print(outcome.result.model_dump_json(indent=2))

    a = outcome.result
    assert a.manipulation_score >= 50, "the benchmark post should not read as neutral"
    assert a.communication_signals, "expected at least one signal"
    assert all(sig.evidence.strip() for sig in a.communication_signals), "every signal needs quoted evidence"
    assert "afd" in a.author_background.lower(), "the supplied source should ground the biography"
