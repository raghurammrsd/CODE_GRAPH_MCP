"""Tests for context caching and repository generation fingerprinting."""
import sqlite3

import pytest

from codegraph.cache import (
    compute_context_cache_key,
    get_cached_context_packet,
    invalidate_context_cache,
    store_cached_context_packet,
)
from codegraph.indexing.indexer import SCHEMA
from codegraph.task import TaskSpec


@pytest.fixture
def cache_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def test_compute_context_cache_key_determinism() -> None:
    spec1 = TaskSpec(goal="Explain authentication", intent="UNDERSTAND", targets=("auth",))
    spec2 = TaskSpec(goal="Explain authentication", intent="UNDERSTAND", targets=("auth",))

    k1 = compute_context_cache_key(spec1, repository_generation=1, max_tokens=4000)
    k2 = compute_context_cache_key(spec2, repository_generation=1, max_tokens=4000)
    assert k1 == k2
    assert k1.startswith("ctx:")

    # Generation increment changes key
    k_gen2 = compute_context_cache_key(spec1, repository_generation=2, max_tokens=4000)
    assert k1 != k_gen2

    # Token budget change changes key
    k_tok = compute_context_cache_key(spec1, repository_generation=1, max_tokens=2000)
    assert k1 != k_tok

    # Parser version change changes key
    k_parser = compute_context_cache_key(spec1, repository_generation=1, max_tokens=4000, parser_version="9.9.9")
    assert k1 != k_parser


def test_store_and_get_cached_context_packet(cache_db: sqlite3.Connection) -> None:
    cache_key = "ctx:abcdef123456"
    packet_data = {
        "task": "Test task",
        "files": [{"file": "src/test.py", "tokens": 100}],
        "budget": {"selected_tokens": 100},
    }

    # Cache miss
    assert get_cached_context_packet(cache_db, cache_key) is None

    # Store
    store_cached_context_packet(cache_db, cache_key, packet_data)

    # Cache hit
    retrieved = get_cached_context_packet(cache_db, cache_key)
    assert retrieved is not None
    assert retrieved["task"] == "Test task"
    assert len(retrieved["files"]) == 1


def test_invalidate_context_cache(cache_db: sqlite3.Connection) -> None:
    cache_key = "ctx:abcdef123456"
    store_cached_context_packet(cache_db, cache_key, {"task": "dummy"})
    assert get_cached_context_packet(cache_db, cache_key) is not None

    invalidate_context_cache(cache_db)
    assert get_cached_context_packet(cache_db, cache_key) is None
