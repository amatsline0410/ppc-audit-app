"""LLM provider abstraction. The whole app runs without any of this.

One interface: .complete(prompt) -> str. Concrete providers in providers.py.
Pick via config.LLM_PROVIDER. 'none' returns a NullProvider that explains it's
disabled (so the UI degrades gracefully instead of erroring).
"""
from __future__ import annotations
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str:
        ...

    def available(self) -> bool:
        """Cheap liveness check; override per provider."""
        return True


class NullProvider(LLMProvider):
    """Default when LLM_PROVIDER=none. No network, no dependency."""
    name = "none"

    def complete(self, prompt: str, system: str | None = None) -> str:
        return ("[LLM disabled] Set LLM_PROVIDER=ollama|lmstudio|openclaw and a model "
                "to enable AI narration. The audit itself works fully without it.")

    def available(self) -> bool:
        return False
