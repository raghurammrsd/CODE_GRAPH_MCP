from __future__ import annotations

from codegraph.resources import BoundedMemoryCache


def test_bounded_memory_cache_lru_item_limit() -> None:
    cache = BoundedMemoryCache[str, str](max_items=3, max_bytes=10_000)
    cache.set("a", "val_a")
    cache.set("b", "val_b")
    cache.set("c", "val_c")

    assert cache.get("a") == "val_a"
    # Accessing "a" makes it MRU. Next insert should evict "b".
    cache.set("d", "val_d")

    assert cache.get("a") == "val_a"
    assert cache.get("b") is None  # Evicted!
    assert cache.get("c") == "val_c"
    assert cache.get("d") == "val_d"


def test_bounded_memory_cache_memory_byte_limit() -> None:
    # 100 bytes max capacity
    cache = BoundedMemoryCache[str, str](max_items=100, max_bytes=100)
    # Put 60 bytes
    cache.put("x", "x" * 60, size_bytes=60)
    assert cache.get("x") is not None

    # Put another 60 bytes -> exceeding 100 bytes -> evicts "x"
    cache.put("y", "y" * 60, size_bytes=60)
    assert cache.get("x") is None
    assert cache.get("y") == "y" * 60


def test_bounded_memory_cache_invalidation() -> None:
    cache = BoundedMemoryCache[str, int](max_items=10)
    cache.set("apple", 1)
    cache.set("apricot", 2)
    cache.set("banana", 3)

    removed = cache.invalidate(lambda k: k.startswith("ap"))
    assert removed == 2
    assert cache.get("apple") is None
    assert cache.get("apricot") is None
    assert cache.get("banana") == 3
