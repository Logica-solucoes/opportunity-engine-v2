"""Pluggable LLM access for the engine and the API. Add a provider: write llm/<name>.py and register it below."""

import os

from llm.base import LLM, LLMBadOutput, LLMError, LLMRefused, LLMUnavailable
from llm.gemini import GeminiLLM

PROVIDERS: dict[str, type] = {"gemini": GeminiLLM}

__all__ = ["LLM", "LLMBadOutput", "LLMError", "LLMRefused", "LLMUnavailable", "PROVIDERS", "get_llm"]


def get_llm(provider: str | None = None, model: str | None = None) -> LLM | None:
    """The configured LLM, or None when disabled (LLM_PROVIDER=none) or the provider has no credentials."""
    name = provider or os.environ.get("LLM_PROVIDER", "gemini")
    if name == "none":
        return None
    if name not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider {name!r}; available: {', '.join(PROVIDERS)} or 'none'")
    return PROVIDERS[name].from_env(model or os.environ.get("LLM_MODEL") or None)
