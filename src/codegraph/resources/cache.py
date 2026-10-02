"""Bounded LRU Memory Caches with Size Tracking and Eviction.

Prevents unbounded memory growth from ParseResults, graph neighborhoods,
and retrieval artifacts during sustained coding sessions.
"""
from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


def _approx_size(obj: Any) -> int:
    """Approximate memory footprint of an object."""
    try:
        if isinstance(obj, (str, bytes)):
            return len(obj)
        elif hasattr(obj, "__sizeof__"):
            return int(obj.__sizeof__())
        return sys.getsizeof(obj, 128)
    except Exception:
        return 128


class BoundedMemoryCache[K, V]:
    """Thread-safe LRU cache with both item count and memory byte limits."""

    def __init__(self, max_items: int = 500, max_bytes: int = 50 * 1024 * 1024) -> None:
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._cache: OrderedDict[K, tuple[V, int]] = OrderedDict()
        self._current_bytes: int = 0
        self._hits: int = 0
        self._misses: int = 0

    def get(self, key: K) -> V | None:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            val, size = self._cache.pop(key)
            self._cache[key] = (val, size)  # move to end (MRU)
            self._hits += 1
            return val

    def put(self, key: K, value: V, size_bytes: int | None = None) -> None:
        sz = size_bytes if size_bytes is not None else _approx_size(value)
        with self._lock:
            if key in self._cache:
                _, old_sz = self._cache.pop(key)
                self._current_bytes -= old_sz

            self._cache[key] = (value, sz)
            self._current_bytes += sz

            # Evict until limits are satisfied
            while len(self._cache) > self.max_items or (self._current_bytes > self.max_bytes and len(self._cache) > 1):
                _, (_, evicted_sz) = self._cache.popitem(last=False)  # pop LRU
                self._current_bytes -= evicted_sz

    def set(self, key: K, value: V, size_bytes: int | None = None) -> None:
        """Alias for put."""
        self.put(key, value, size_bytes)

    def invalidate(self, predicate: Callable[[K], bool]) -> int:
        removed = 0
        with self._lock:
            keys_to_del = [k for k in self._cache if predicate(k)]
            for k in keys_to_del:
                _, sz = self._cache.pop(k)
                self._current_bytes -= sz
                removed += 1
        return removed

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._current_bytes = 0

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "items": len(self._cache),
                "max_items": self.max_items,
                "current_mb": round(self._current_bytes / (1024 * 1024), 2),
                "max_mb": round(self.max_bytes / (1024 * 1024), 2),
                "hits": self._hits,
                "misses": self._misses,
            }


# ---------------------------------------------------------------------------
# Global Specialized Caches
# ---------------------------------------------------------------------------

# ParseResult cache: (source_hash, parser_version, language) -> ParseResult
_PARSE_CACHE: BoundedMemoryCache[tuple[str, str, str], Any] = BoundedMemoryCache(
    max_items=300,
    max_bytes=30 * 1024 * 1024,  # 30 MB
)

# Graph neighborhood cache: (repo_generation, symbol_id, relationship, depth) -> list[dict]
_GRAPH_CACHE: BoundedMemoryCache[tuple[int, str, str, int], Any] = BoundedMemoryCache(
    max_items=500,
    max_bytes=20 * 1024 * 1024,  # 20 MB
)


def get_parse_cache() -> BoundedMemoryCache[tuple[str, str, str], Any]:
    return _PARSE_CACHE


def get_graph_cache() -> BoundedMemoryCache[tuple[int, str, str, int], Any]:
    return _GRAPH_CACHE
