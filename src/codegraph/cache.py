"""Deterministic Task Fingerprinting and Context Caching Engine.

Guarantees repository generation consistency and cache invalidation on:
- Source code or index generation change
- Parser version change
- Database schema change
- Configuration change
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, cast

from codegraph.indexing.parser import PARSER_VERSION
from codegraph.task import TaskSpec

CACHE_SCHEMA_VERSION = 1


def compute_context_cache_key(
    task_spec: TaskSpec,
    repository_generation: int,
    max_tokens: int,
    parser_version: str = PARSER_VERSION,
    extra_config: str = "",
) -> str:
    """Compute an immutable, deterministic cache key for a context compilation request."""
    canonical_components = {
        "intent": task_spec.intent,
        "goal": task_spec.goal,
        "targets": sorted(task_spec.targets),
        "operations": sorted(task_spec.operations),
        "constraints": sorted(task_spec.constraints),
        "exclusions": sorted(task_spec.exclusions),
        "scope_paths": sorted(task_spec.scope_paths),
        "time_scope": task_spec.time_scope or "",
        "repository_generation": repository_generation,
        "max_tokens": max_tokens,
        "parser_version": parser_version,
        "cache_schema": CACHE_SCHEMA_VERSION,
        "extra_config": extra_config,
    }
    raw = json.dumps(canonical_components, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"ctx:{hashlib.sha256(raw).hexdigest()}"


def get_cached_context_packet(
    con: sqlite3.Connection,
    cache_key: str,
) -> dict[str, Any] | None:
    """Retrieve cached context packet if present in SQLite context_cache."""
    try:
        row = con.execute(
            "SELECT data FROM context_cache WHERE cache_key=?",
            (cache_key,),
        ).fetchone()
        if row:
            raw_data = row["data"] if isinstance(row, sqlite3.Row) else row[0]
            parsed = json.loads(raw_data)
            if isinstance(parsed, dict):
                return cast(dict[str, Any], parsed)
            return None
    except Exception:
        pass
    return None


def store_cached_context_packet(
    con: sqlite3.Connection,
    cache_key: str,
    packet_dict: dict[str, Any],
) -> None:
    """Store compiled ContextPacket in SQLite context_cache table."""
    try:
        now = int(time.time())
        serialized = json.dumps(packet_dict, sort_keys=True)
        con.execute(
            "INSERT OR REPLACE INTO context_cache (cache_key, data, created_at) VALUES (?, ?, ?)",
            (cache_key, serialized, now),
        )
        con.commit()
    except Exception:
        pass


def invalidate_context_cache(con: sqlite3.Connection) -> None:
    """Explicitly wipe context cache upon repository mutation or index generation advancement."""
    try:
        con.execute("DELETE FROM context_cache")
        con.commit()
    except Exception:
        pass
