"""In-memory TTL cache. Protects the Gemini free-tier daily quota from repeat clicks.

Single-process only. Swap for Redis/SQLite before hosting multi-worker.
"""

from __future__ import annotations

import hashlib
import time
from typing import Generic, TypeVar

T = TypeVar("T")


def make_key(author_handle: str, post_text: str) -> str:
    raw = f"{author_handle.lower().strip()}\n{post_text.strip()}".encode()
    return hashlib.sha256(raw).hexdigest()


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: int, max_items: int = 2_000) -> None:
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._store: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: T) -> None:
        if len(self._store) >= self.max_items:
            self._evict()
        self._store[key] = (time.monotonic() + self.ttl, value)

    def clear(self) -> None:
        self._store.clear()

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
