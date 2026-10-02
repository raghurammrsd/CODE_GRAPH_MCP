from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """An external model provider could not complete a request."""


class LLMProvider(ABC):
    """Provider-neutral interface; CodeGraph works without a configured provider."""

    @abstractmethod
    async def complete(self, prompt: str, context: str) -> str:
        raise NotImplementedError
