from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import CallRef, Chunk, ImportRef, Symbol

if TYPE_CHECKING:
    from .indexer import Indexer

__all__ = ["CallRef", "Chunk", "ImportRef", "Indexer", "Symbol"]


def __getattr__(name: str) -> Any:
    if name == "Indexer":
        from .indexer import Indexer

        return Indexer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
