"""The drawer only reaches the backend if CORS lets the extension's origin through.

Chrome gives the extension a 32-letter id, Firefox a fresh moz-extension UUID per profile.
x.com itself must stay blocked: that is the reason background.js exists.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app

CHROME = "chrome-extension://" + "a" * 32
FIREFOX = "moz-extension://3f2504e0-4f89-41d3-9a0c-0305e82c3301"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def preflight(client: TestClient, origin: str) -> str | None:
    res = client.options(
        "/api/v1/claims",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    return res.headers.get("access-control-allow-origin")


@pytest.mark.parametrize("origin", [CHROME, FIREFOX, "http://localhost:3000", "http://127.0.0.1:8000"])
def test_allowed_origins(client: TestClient, origin: str) -> None:
    assert preflight(client, origin) == origin


@pytest.mark.parametrize("origin", ["https://x.com", "moz-extension://not-a-uuid", "chrome-extension://short"])
def test_blocked_origins(client: TestClient, origin: str) -> None:
    assert preflight(client, origin) is None
