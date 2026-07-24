"""Optional LangChain bridge. Only imported when LLM_USE_LANGCHAIN=true.

Wraps any LLMProvider as a LangChain Runnable so you can drop it into chains,
prompt templates, RAG, agents, etc. If langchain isn't installed, get_provider()
catches the ImportError and falls back to the raw provider.
"""
from __future__ import annotations
from .base import LLMProvider


def wrap(provider: LLMProvider):
    from langchain_core.language_models.llms import LLM
    from langchain_core.runnables import RunnableLambda  # noqa: F401 (available for chains)

    class _Wrapped(LLM):
        @property
        def _llm_type(self) -> str:
            return f"ppc-{provider.name}"

        def _call(self, prompt: str, stop=None, run_manager=None, **kwargs) -> str:
            return provider.complete(prompt)

    w = _Wrapped()
    # keep the provider interface too, so narrate.py can call .complete uniformly
    w.complete = lambda prompt, system=None: provider.complete(prompt, system)  # type: ignore
    w.available = provider.available                                            # type: ignore
    w.name = provider.name                                                      # type: ignore
    return w
