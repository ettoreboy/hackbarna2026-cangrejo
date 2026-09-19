"""Mock transport for the Nebius chat endpoint.

The openai SDK (3.x) ships its own vendored HTTP stack, ``httpx2``, so respx — which patches
``httpx`` — never sees its traffic. Requests to Wikipedia and Brave still go through plain
httpx and are still mocked with respx; only the model endpoint needs this.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx2
from openai import AsyncOpenAI

CHAT_PATH = "/v1/chat/completions"


def chat_completion(
    content: str | dict[str, Any],
    *,
    model: str = "Qwen/Qwen3-32B",
    prompt_tokens: int = 1200,
    completion_tokens: int = 300,
    finish_reason: str = "stop",
) -> httpx2.Response:
    if isinstance(content, dict):
        content = json.dumps(content)
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1_758_000_000,
            "model": model,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        },
    )


def api_error(status: int, message: str) -> httpx2.Response:
    return httpx2.Response(status, json={"error": {"message": message, "type": "invalid_request_error"}})


class MockChatServer:
    """Queued responses plus a record of every request body that was sent."""

    def __init__(self, *responses: httpx2.Response | Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def body(self, index: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[index].content)

    def _handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(f"unexpected extra request to {request.url}")
        nxt = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return nxt(request) if callable(nxt) else nxt

    def client(self, *, api_key: str = "test-key", base_url: str = "https://api.tokenfactory.nebius.com/v1/") -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self._handler)),
        )
