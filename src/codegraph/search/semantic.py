from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class SemanticSearchUnavailable(RuntimeError):
    """No embedding provider has been configured for semantic retrieval."""


class EmbeddingProvider(ABC):
    """Provider-neutral embeddings interface; implementations must be deterministic in tests."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


@dataclass(frozen=True)
class SemanticStatus:
    available: bool
    detail: str


def status(provider: EmbeddingProvider | None) -> SemanticStatus:
    if provider is None:
        return SemanticStatus(False, "No embedding provider configured; lexical and symbol retrieval remain active.")
    return SemanticStatus(True, "Embedding provider configured.")
