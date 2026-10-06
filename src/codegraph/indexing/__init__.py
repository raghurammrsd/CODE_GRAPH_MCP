from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import CallRef, Chunk, ImportRef, Symbol

if TYPE_CHECKING:
    from .indexer import Indexer
    from .pool import SQLiteConnectionPool

__all__ = ["CallRef", "Chunk", "ImportRef", "Indexer", "SQLiteConnectionPool", "Symbol"]


def __getattr__(name: str) -> Any:
    if name == "Indexer":
        from .indexer import Indexer

        return Indexer
    if name == "SQLiteConnectionPool":
        from .pool import SQLiteConnectionPool

        return SQLiteConnectionPool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

