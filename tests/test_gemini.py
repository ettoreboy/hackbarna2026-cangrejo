"""Gemini provider, basic: determinism, request shape, JSON salvage, failure modes, cost.

The baseline provider had no tests before the comparison work; these lock in the parity with
NebiusAnalyzer that a side-by-side comparison depends on. No API key is needed.
"""

from __future__ import annotations

import os

import pytest

from backend.config import Settings
from backend.schemas.analysis_schema import AnalysisBody, AnalyzeRequest, MainClaim
from backend.services.analyzer_base import AnalysisError
from backend.services.gemini_service import GeminiAnalyzer
from tests.conftest import FIXTURES
from tests.gemini_mock import MockGeminiClient, blocked, parsed_ok, text_only, truncated

CLAIM = MainClaim(
    found=True,
    text="Germany accepted 1.2 million migrants last year.",
    quote="Germany accepted 1.2M migrants last year.",
)
BODY_JSON = {
    "claim_check": {"verdict": "partially_supported", "explanation": "Close, but the figure mixes categories.", "sources": []},
    "missing_context": "Includes Ukrainian refugees under temporary protection.",
    "rhetorical_signals": [{"name": "Loaded language", "evidence": "clearly doesn't care"}],
    "speaker_context": {"name": "Example Account", "role": "", "background": "Unknown author"},
}


def settings(**over) -> Settings:
    base = {"ANALYZER_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-2.5-flash", "NEBIUS_API_KEY": ""}
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def req() -> AnalyzeRequest:
    return AnalyzeRequest(**FIXTURES["spec_example"]["request"])


async def test_missing_key_is_rejected_at_construction():
    with pytest.raises(AnalysisError, match="GEMINI_API_KEY"):
        GeminiAnalyzer(settings(GEMINI_API_KEY=""))


async def test_temperature_defaults_to_zero_for_reproducibility():
    """A comparison run must measure the prompt or the provider, not sampling noise."""
    client = MockGeminiClient(parsed_ok(CLAIM))
    a = GeminiAnalyzer(settings(), client=client)
    await a.extract_claim(req())
    assert a.temperature == 0.0
    assert client.config(0).temperature == 0.0


async def test_temperature_is_configurable():
    client = MockGeminiClient(parsed_ok(CLAIM))
    a = GeminiAnalyzer(settings(GEMINI_TEMPERATURE=0.7), client=client)
    await a.extract_claim(req())
    assert client.config(0).temperature == 0.7


async def test_both_steps_send_the_schema_and_parse():
    client = MockGeminiClient(parsed_ok(CLAIM), text_only(BODY_JSON))
    a = GeminiAnalyzer(settings(), client=client)

    claim = (await a.extract_claim(req())).result
    assert claim.found and claim.quote == CLAIM.quote
    cfg = client.config(0)
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema is MainClaim
    assert cfg.max_output_tokens == 300
    assert "<post>" in client.calls[0]["contents"]

    body = (await a.analyse(req(), claim, [], [], prompt_version="v1")).result
    assert body.claim_check.verdict == "partially_supported"
    assert body.rhetorical_signals[0].name == "Loaded Language", "synonym normalised"
    assert client.config(1).response_schema is AnalysisBody
    assert client.config(1).max_output_tokens == 900
    assert "RULES:" in client.config(1).system_instruction


async def test_fenced_json_is_salvaged():
    """A model that drops out of JSON mode wraps the object in a fence; do not lose the answer."""
    fenced = '```json\n{"found": true, "text": "A claim.", "quote": "A claim."}\n```'
    client = MockGeminiClient(text_only(fenced))
    a = GeminiAnalyzer(settings(), client=client)
    claim = (await a.extract_claim(req())).result
    assert claim.found and claim.text == "A claim."


async def test_unsalvageable_output_is_an_error():
    client = MockGeminiClient(text_only("I am afraid I cannot help with that."))
    a = GeminiAnalyzer(settings(), client=client)
    with pytest.raises(AnalysisError, match="does not match the schema"):
        await a.extract_claim(req())


async def test_truncated_reply_is_an_error():
    client = MockGeminiClient(truncated('{"found": true, "text": "cut'))
    a = GeminiAnalyzer(settings(), client=client)
    with pytest.raises(AnalysisError, match="token limit"):
        await a.extract_claim(req())


async def test_safety_block_says_so():
    client = MockGeminiClient(blocked())
    a = GeminiAnalyzer(settings(), client=client)
    with pytest.raises(AnalysisError, match="safety filter"):
        await a.extract_claim(req())


async def test_sdk_failure_is_wrapped():
    client = MockGeminiClient(RuntimeError("503 backend unavailable"))
    a = GeminiAnalyzer(settings(), client=client)
    with pytest.raises(AnalysisError, match="Gemini call failed"):
        await a.extract_claim(req())


async def test_cost_is_reported_for_a_priced_model():
    client = MockGeminiClient(parsed_ok(CLAIM, prompt_tokens=1_000_000, completion_tokens=0))
    a = GeminiAnalyzer(settings(), client=client)
    assert (await a.extract_claim(req())).cost_usd == pytest.approx(0.30)  # gemini-2.5-flash input price


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")
async def test_live_spec_example():
    """One real two-step run of the example post, the baseline arm of the comparison."""
    a = GeminiAnalyzer(Settings(_env_file=None))  # type: ignore[call-arg]
    claim = (await a.extract_claim(req())).result
    print("\nclaim:", claim.model_dump())
    assert claim.found and "1.2" in claim.text
    body = (await a.analyse(req(), claim, [], [])).result
    print(body.model_dump_json(indent=2))
    assert body.claim_check.verdict == "unverifiable", "no evidence supplied, so no stronger verdict"
