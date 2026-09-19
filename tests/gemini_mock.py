"""Mock client for the Gemini analyzer.

google-genai, like the openai SDK, does not go through plain httpx in a way respx can
intercept, and its client wants a key at construction time. ``GeminiAnalyzer`` therefore takes
an injectable client (same as ``NebiusAnalyzer``) and this module supplies a duck-typed stand-in:
the analyzer only ever touches ``client.aio.models.generate_content``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class _Usage:
    prompt_token_count: int = 1200
    candidates_token_count: int = 300


@dataclass
class _Candidate:
    finish_reason: str | None = "STOP"


@dataclass
class FakeResponse:
    """Shaped like google.genai GenerateContentResponse, for the three fields we read."""

    parsed: BaseModel | None = None
    text: str | None = None
    candidates: list[_Candidate] = field(default_factory=lambda: [_Candidate()])
    usage_metadata: _Usage = field(default_factory=_Usage)


def parsed_ok(model: BaseModel, *, prompt_tokens: int = 1200, completion_tokens: int = 300) -> FakeResponse:
    """The normal path: the SDK validated the schema for us."""
    return FakeResponse(parsed=model, text=model.model_dump_json(), usage_metadata=_Usage(prompt_tokens, completion_tokens))


def text_only(content: str | dict[str, Any], *, finish_reason: str = "STOP") -> FakeResponse:
    """The SDK could not build the object, so the analyzer has to parse the text itself."""
    if isinstance(content, dict):
        content = json.dumps(content)
    return FakeResponse(parsed=None, text=content, candidates=[_Candidate(finish_reason)])


def blocked() -> FakeResponse:
    """Safety filter: no candidate content at all."""
    return FakeResponse(parsed=None, text=None, candidates=[_Candidate("SAFETY")])


def truncated(partial: str) -> FakeResponse:
    return FakeResponse(parsed=None, text=partial, candidates=[_Candidate("MAX_TOKENS")])


class _Models:
    def __init__(self, owner: "MockGeminiClient") -> None:
        self._owner = owner

    async def generate_content(self, *, model: str, contents: str, config: Any) -> FakeResponse:
        self._owner.calls.append({"model": model, "contents": contents, "config": config})
        if not self._owner.responses:
            raise AssertionError("unexpected extra call to generate_content")
        nxt = self._owner.responses.pop(0) if len(self._owner.responses) > 1 else self._owner.responses[0]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class _Aio:
    def __init__(self, owner: "MockGeminiClient") -> None:
        self.models = _Models(owner)


class MockGeminiClient:
    """Queued responses plus a record of every call the analyzer made."""

    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self.responses: list[Any] = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.aio = _Aio(self)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def config(self, index: int = 0) -> Any:
        return self.calls[index]["config"]
