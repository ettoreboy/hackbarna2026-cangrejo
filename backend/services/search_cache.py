"""Disk cache and spend counter for Brave Search.

Brave is prepaid ($5 per 1 000 requests). Every eval re-run, every fine-tune data pass and
every demo click would otherwise hit the meter again. Results are stored in SQLite keyed by
the normalised query, with no expiry during the hackathon, and every live call is counted so
a hard budget can stop the bleeding.

Synchronous sqlite3 is fine here: calls are rare and sub-millisecond.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

_WS = re.compile(r"\s+")


def normalise(query: str) -> str:
    return _WS.sub(" ", query.strip().lower())


class SearchCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY, query TEXT, payload TEXT, created REAL)"
        )
        self._conn.execute("CREATE TABLE IF NOT EXISTS live_calls (id INTEGER PRIMARY KEY, query TEXT, created REAL)")
        self._conn.commit()

    def get(self, query: str) -> list[dict] | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM results WHERE key = ?", (normalise(query),)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, query: str, results: list[dict]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO results (key, query, payload, created) VALUES (?, ?, ?, ?)",
                (normalise(query), query, json.dumps(results), time.time()),
            )
            self._conn.commit()

    def record_live_call(self, query: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO live_calls (query, created) VALUES (?, ?)", (query, time.time()))
            self._conn.commit()

    def live_calls(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM live_calls").fetchone()[0])

    def cached_queries(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class NullCache(SearchCache):
    """In-memory stand-in for tests and for when no cache path is configured."""

    def __init__(self) -> None:  # noqa: D107
        self.path = Path(":memory:")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute("CREATE TABLE results (key TEXT PRIMARY KEY, query TEXT, payload TEXT, created REAL)")
        self._conn.execute("CREATE TABLE live_calls (id INTEGER PRIMARY KEY, query TEXT, created REAL)")
        self._conn.commit()
