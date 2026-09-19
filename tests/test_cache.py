"""The response cache, and the one thing it is for: the same post answering the same way twice.

The model is not reproducible (see backend/services/cache.py), so surviving a restart is what
makes a demo repeatable. These tests are about the disk half; the in-memory half is exercised
everywhere else in the suite.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.schemas.analysis_schema import ClaimCandidate, ClaimsResponse, SpeakerContext
from backend.services.cache import TTLCache, make_key

MODELS = {"ClaimsResponse": ClaimsResponse}


def a_response(claim: str) -> ClaimsResponse:
    return ClaimsResponse(
        claims=[ClaimCandidate(id="c1", text=claim, quote=claim)],
        speaker_context=SpeakerContext(name="Someone", role="", background="unknown author"),
        provider="nebius",
        model="openai/gpt-oss-120b",
    )


def test_memory_only_is_the_default(tmp_path):
    cache: TTLCache[ClaimsResponse] = TTLCache(ttl_seconds=60)
    cache.set("k", a_response("the streets are less safe"))
    assert cache.get("k") is not None
    assert cache.stored() == 0, "nothing should be written without a path"
    assert not list(tmp_path.iterdir())


def test_an_entry_survives_a_restart(tmp_path):
    """The whole point: analyse once, and every later view returns that same answer."""
    path = tmp_path / "responses.sqlite"
    first: TTLCache[ClaimsResponse] = TTLCache(ttl_seconds=3600, path=path, models=MODELS)
    first.set(make_key("alice_weidel", "post"), a_response("the streets are less safe"))
    assert first.stored() == 1
    first.close()

    # A new process: empty memory, same file.
    second: TTLCache[ClaimsResponse] = TTLCache(ttl_seconds=3600, path=path, models=MODELS)
    assert len(second) == 0
    got = second.get(make_key("alice_weidel", "post"))
    assert got is not None
    assert got.claims[0].text == "the streets are less safe"
    assert got.model == "openai/gpt-oss-120b"
    assert len(second) == 1, "a disk hit should be promoted into memory"
    second.close()


def test_an_expired_row_is_not_served(tmp_path):
    path = tmp_path / "responses.sqlite"
    cache: TTLCache[ClaimsResponse] = TTLCache(ttl_seconds=0, path=path, models=MODELS)
    cache.set("k", a_response("stale"))
    cache.clear()  # drop the memory copy but keep the file open
    assert cache.get("k") is None
    assert cache.stored() == 0, "an expired row should be deleted on the way out"
    cache.close()


def test_a_row_of_an_unknown_type_is_ignored_not_raised(tmp_path):
    """A schema change must degrade to a cache miss, never to a 500."""
    path = tmp_path / "responses.sqlite"
    cache: TTLCache[ClaimsResponse] = TTLCache(ttl_seconds=3600, path=path, models=MODELS)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO responses (key, kind, payload, expires) VALUES (?, ?, ?, ?)",
        ("k", "SomethingFromAnOlderVersion", "{}", 9e12),
    )
    conn.commit()
    conn.close()
    assert cache.get("k") is None
    cache.close()


def test_an_unreadable_payload_is_ignored_not_raised(tmp_path):
    path = tmp_path / "responses.sqlite"
    cache: TTLCache[ClaimsResponse] = TTLCache(ttl_seconds=3600, path=path, models=MODELS)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO responses (key, kind, payload, expires) VALUES (?, ?, ?, ?)",
        ("k", "ClaimsResponse", '{"claims": "not a list"}', 9e12),
    )
    conn.commit()
    conn.close()
    assert cache.get("k") is None
    cache.close()


def test_a_disk_cache_without_models_is_refused(tmp_path):
    """Silently falling back to memory would look like it worked and lose every row."""
    with pytest.raises(ValueError, match="models"):
        TTLCache(ttl_seconds=60, path=tmp_path / "x.sqlite")
