"""Concrete local-LLM providers. All talk to localhost by default.

- OllamaProvider     : native Ollama HTTP API (/api/generate)
- LMStudioProvider   : LM Studio's OpenAI-compatible server (/v1/chat/completions)
- OpenAICompatProvider: any OpenAI-compatible endpoint (vLLM, llama.cpp server, etc.)
- OpenClawProvider   : OpenClaw agent CLI via subprocess

Factory get_provider() reads config and returns the right one, or NullProvider.
requests is imported lazily so the app installs/runs even if it's absent.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from .base import LLMProvider, NullProvider
from ..config import settings


class _HTTPMixin:
    def _requests(self):
        import requests  # lazy
        return requests


class OllamaProvider(_HTTPMixin, LLMProvider):
    name = "ollama"
    def __init__(self, model: str, base_url: str = ""):
        self.model = model
        self.base = (base_url or "http://localhost:11434").rstrip("/")

    def complete(self, prompt: str, system: str | None = None) -> str:
        r = self._requests().post(f"{self.base}/api/generate",
            json={"model": self.model, "prompt": prompt, "system": system or "",
                  "stream": False}, timeout=settings.llm_timeout)
        r.raise_for_status()
        return r.json().get("response", "").strip()

    def available(self) -> bool:
        try:
            return self._requests().get(f"{self.base}/api/tags", timeout=3).ok
        except Exception:
            return False


class _OpenAIChat(_HTTPMixin, LLMProvider):
    """Shared logic for OpenAI-compatible /v1/chat/completions servers."""
    default_base = "http://localhost:1234/v1"
    def __init__(self, model: str, base_url: str = ""):
        self.model = model
        self.base = (base_url or self.default_base).rstrip("/")

    def complete(self, prompt: str, system: str | None = None) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        r = self._requests().post(f"{self.base}/chat/completions",
            json={"model": self.model, "messages": msgs, "temperature": 0.3},
            timeout=settings.llm_timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def available(self) -> bool:
        try:
            return self._requests().get(f"{self.base}/models", timeout=3).ok
        except Exception:
            return False


class LMStudioProvider(_OpenAIChat):
    name = "lmstudio"
    default_base = "http://localhost:1234/v1"


class OpenAICompatProvider(_OpenAIChat):
    name = "openai_compat"
    default_base = "http://localhost:8000/v1"


class OpenClawProvider(LLMProvider):
    """OpenClaw agent CLI. Calls `openclaw run -m <model> -p <prompt>`.

    Adjust the argv to match your OpenClaw version if needed — kept in one place.
    """
    name = "openclaw"
    def __init__(self, model: str, base_url: str = ""):
        self.model = model
        self.bin = base_url or "openclaw"  # allow overriding the binary path via LLM_BASE_URL

    def complete(self, prompt: str, system: str | None = None) -> str:
        full = (f"{system}\n\n{prompt}" if system else prompt)
        proc = subprocess.run([self.bin, "run", "-m", self.model, "-p", full],
                              capture_output=True, text=True, timeout=settings.llm_timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"openclaw failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def available(self) -> bool:
        return shutil.which(self.bin) is not None


_REGISTRY = {
    "ollama": OllamaProvider, "lmstudio": LMStudioProvider,
    "openai_compat": OpenAICompatProvider, "openclaw": OpenClawProvider,
}


def get_provider() -> LLMProvider:
    """Factory. Honors LLM_USE_LANGCHAIN by wrapping the base provider."""
    cls = _REGISTRY.get(settings.llm_provider.lower())
    if cls is None:
        return NullProvider()
    provider = cls(settings.llm_model, settings.llm_base_url)
    if settings.llm_use_langchain:
        try:
            from .langchain_adapter import wrap
            return wrap(provider)
        except Exception:
            return provider  # langchain missing -> use raw provider
    return provider
