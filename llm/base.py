"""Provider-neutral LLM interface. Adapters live next to this file; sampling knobs stay inside them."""

from typing import Any, Protocol


class LLMError(Exception):
    """Base for every failure of an LLM call."""


class LLMUnavailable(LLMError):
    """No key, network, timeout, quota or 5xx: try again later or fall back to the deterministic text."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason  # short stable code for logs ("no_key", "rate_limited", "timeout"...)


class LLMRefused(LLMError):
    """The provider declined the request by policy."""


class LLMBadOutput(LLMError):
    """The answer is empty, not valid JSON, or does not fit what was asked."""


class LLM(Protocol):
    provider: str
    model: str

    def generate_text(self, prompt: str, *, timeout_s: float | None = None) -> str: ...

    def generate_json(self, prompt: str, schema: dict, *, timeout_s: float | None = None) -> Any:
        """Parsed JSON; the caller validates it (pydantic)."""
        ...
