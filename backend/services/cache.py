"""TTL cache for analysis responses, in memory and optionally on disk.

Two jobs. It protects the token budget from repeat clicks, and it is the only thing that makes
a given post answer the same way twice.

The model cannot be pinned. Nebius serves gpt-oss-120b from vLLM across four GPUs, where batch
composition changes the order of floating-point reductions, so the same prompt at temperature 0
returns different text run to run -- measured at 1 to 3 rhetorical signals on one post across
five identical calls. `seed` does not help: five calls at seed=7 gave five distinct answers.

So consistency comes from answering a post once and keeping the answer. With `path` set, entries
survive a restart, which is what turns "run it again and hope" into a demo that shows the same
thing every time. Values must be pydantic models, and `models` maps a class name back to its
class so a stored row can be rehydrated.

Still single-process for writes; SQLite handles concurrent readers fine.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Generic, Mapping, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


def make_key(author_handle: str, post_text: str) -> str:
    raw = f"{author_handle.lower().strip()}\n{post_text.strip()}".encode()
    return hashlib.sha256(raw).hexdigest()


class TTLCache(Generic[T]):
    def __init__(
        self,
        ttl_seconds: int,
        max_items: int = 2_000,
        path: str | Path | None = None,
        models: Mapping[str, type] | None = None,
    ) -> None:
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._store: dict[str, tuple[float, T]] = {}
        self._models = dict(models or {})
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if path:
            if not self._models:
                raise ValueError("a disk-backed TTLCache needs `models` to rehydrate stored rows")
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(p, check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, kind TEXT, payload TEXT, expires REAL)"
            )
            self._conn.commit()

    def get(self, key: str) -> T | None:
        item = self._store.get(key)
        if item is not None:
            expires_at, value = item
            # Memory expiry is monotonic: immune to the wall clock being adjusted.
            if expires_at >= time.monotonic():
                return value
            self._store.pop(key, None)
        return self._load(key)

    def set(self, key: str, value: T) -> None:
        if len(self._store) >= self.max_items:
            self._evict()
        self._store[key] = (time.monotonic() + self.ttl, value)
        self._save(key, value)

    def clear(self) -> None:
        self._store.clear()
        if self._conn is not None:
            with self._lock:
                self._conn.execute("DELETE FROM responses")
                self._conn.commit()

    # ------------------------------------------------------------------ disk

    def _save(self, key: str, value: Any) -> None:
        if self._conn is None:
            return
        dump = getattr(value, "model_dump_json", None)
        if dump is None:
            return  # not a pydantic model; memory only, no reason to fail the request
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO responses (key, kind, payload, expires) VALUES (?, ?, ?, ?)",
                    (key, type(value).__name__, dump(), time.time() + self.ttl),
                )
                self._conn.commit()
        except sqlite3.Error as exc:  # a cache is never worth failing a request over
            log.warning("response cache write failed: %s", exc)

    def _load(self, key: str) -> T | None:
        if self._conn is None:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT kind, payload, expires FROM responses WHERE key = ?", (key,)
                ).fetchone()
        except sqlite3.Error as exc:
            log.warning("response cache read failed: %s", exc)
            return None
        if row is None:
            return None
        kind, payload, expires = row
        # Disk expiry is wall clock: a monotonic clock restarts with the process.
        if expires < time.time():
            with self._lock:
                self._conn.execute("DELETE FROM responses WHERE key = ?", (key,))
                self._conn.commit()
            return None
        model = self._models.get(kind)
        if model is None:
            log.warning("response cache holds unknown type %r; ignoring", kind)
            return None
        try:
            value = model.model_validate(json.loads(payload))
        except Exception as exc:  # a schema change makes old rows unreadable, not fatal
            log.warning("response cache row for %s is unreadable (%s); ignoring", kind, exc)
            return None
        self._store[key] = (time.monotonic() + self.ttl, value)
        return value

    def stored(self) -> int:
        """Rows on disk, for `make status`. Zero when memory only."""
        if self._conn is None:
            return 0
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0])

    def close(self) -> None:
        if self._conn is not None:
            with self._lock:
                self._conn.close()
            self._conn = None

    def __len__(self) -> int:
        return len(self._store)

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if exp < now]
        for k in expired:
            self._store.pop(k, None)
        if len(self._store) >= self.max_items:
            # Drop the oldest quarter by expiry time.
            oldest = sorted(self._store.items(), key=lambda kv: kv[1][0])[: self.max_items // 4]
            for k, _ in oldest:
                self._store.pop(k, None)
