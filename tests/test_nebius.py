"""Nebius provider, basic: request shape, strict-mode fallback, error handling, cost.

The model endpoint is driven through a mock transport (tests/nebius_mock.py) because the
openai SDK uses its own vendored HTTP stack. No API key is needed.
"""

from __future__ import annotations

import os

import pytest

from backend.config import Settings
from backend.schemas.analysis_schema import AnalyzeRequest, MainClaim
from backend.services.analyzer_base import AnalysisError
from backend.services.nebius_service import NebiusAnalyzer
from tests.conftest import FIXTURES
from tests.nebius_mock import MockChatServer, api_error, chat_completion

CLAIM = {"found": True, "text": "Germany accepted 1.2 million migrants last year.", "quote": "Germany accepted 1.2M migrants last year."}
BODY = {
    "claim_check": {"verdict": "partially_supported", "explanation": "Close but the figure mixes categories.", "sources": []},
    "missing_context": "Includes Ukrainian refugees under temporary protection.",
    "rhetorical_signals": [{"name": "Loaded language", "evidence": "clearly doesn't care"}],
    "speaker_context": {"name": "Example Account", "role": "", "background": "Unknown author"},
}


def settings(**over) -> Settings:
    base = {"ANALYZER_PROVIDER": "nebius", "NEBIUS_API_KEY": "test-key", "NEBIUS_MODEL": "openai/gpt-oss-120b", "GEMINI_API_KEY": ""}
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def req() -> AnalyzeRequest:
    return AnalyzeRequest(**FIXTURES["spec_example"]["request"])


async def test_both_steps_send_strict_schema_and_parse():
    server = MockChatServer(chat_completion(CLAIM), chat_completion(BODY))
    a = NebiusAnalyzer(settings(), client=server.client())

    claim = (await a.extract_claim(req())).result
    assert claim.found and claim.quote == CLAIM["quote"]
    sent = server.body(0)
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["reasoning_effort"] == "low"
    assert "<post>" in sent["messages"][1]["content"]

    body = (await a.analyse(req(), claim, [], [], prompt_version="v1")).result
    assert body.claim_check.verdict == "partially_supported"
    assert body.rhetorical_signals[0].name == "Loaded Language", "synonym normalised"
    assert "RULES:" in server.body(1)["messages"][0]["content"]


async def test_strict_rejection_falls_back_to_json_object_once_per_model():
    server = MockChatServer(api_error(400, "response_format json_schema not supported"), chat_completion(CLAIM), chat_completion(CLAIM))
    a = NebiusAnalyzer(settings(), client=server.client())
    await a.extract_claim(req())
    await a.extract_claim(req())
    assert server.call_count == 3
    assert server.body(1)["response_format"] == {"type": "json_object"}
    assert "exactly these keys" in server.body(1)["messages"][0]["content"]
    assert server.body(2)["response_format"] == {"type": "json_object"}


async def test_unrelated_error_is_surfaced_without_retry():
    server = MockChatServer(api_error(400, "max_tokens must be a positive integer"))
    a = NebiusAnalyzer(settings(), client=server.client())
    with pytest.raises(AnalysisError, match="Nebius call failed"):
        await a.extract_claim(req())
    assert server.call_count == 1


async def test_truncated_reply_is_an_error():
    server = MockChatServer(chat_completion('{"found": true, "text": "cut', finish_reason="length"))
    a = NebiusAnalyzer(settings(), client=server.client())
    with pytest.raises(AnalysisError, match="token limit"):
        await a.extract_claim(req())


async def test_cost_is_reported_for_a_priced_model():
    server = MockChatServer(chat_completion(CLAIM, prompt_tokens=1_000_000, completion_tokens=0))
    a = NebiusAnalyzer(settings(), client=server.client())
    outcome = await a.extract_claim(req())
    assert outcome.cost_usd == pytest.approx(0.15)  # gpt-oss-120b input price


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("NEBIUS_API_KEY"), reason="NEBIUS_API_KEY not set")
async def test_live_spec_example():
    """One real two-step run of the user's example post."""
    a = NebiusAnalyzer(Settings(_env_file=None))  # type: ignore[call-arg]
    claim = (await a.extract_claim(req())).result
    print("\nclaim:", claim.model_dump())
    assert claim.found and "1.2" in claim.text and "care" not in claim.text.lower()
    body = (await a.analyse(req(), claim, [], [])).result
    print(body.model_dump_json(indent=2))
    assert body.claim_check.verdict == "unverifiable", "no evidence supplied, so no stronger verdict"
    assert body.speaker_context.background == "Unknown author"
