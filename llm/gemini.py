"""Gemini adapter over google-genai (imported lazily so the package loads without the SDK)."""

import json
import logging
import os
from typing import Any

from llm.base import LLMBadOutput, LLMError, LLMRefused, LLMUnavailable

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-latest"  # alias that follows the current Flash; pin a version if outputs drift
TRANSIENT_CODES = {429, 500, 503, 504}


def _client(api_key: str, timeout_s: float | None):
    from google import genai
    from google.genai import types

    options = types.HttpOptions(timeout=int(timeout_s * 1000)) if timeout_s else None
    return genai.Client(api_key=api_key, http_options=options)


def _loads(text: str) -> Any:
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.rsplit("```", 1)[0]
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise LLMBadOutput("invalid_json") from e


class GeminiLLM:
    provider = "gemini"

    def __init__(self, model: str, api_key: str):
        self.model = model
        self._api_key = api_key

    @classmethod
    def from_env(cls, model: str | None) -> "GeminiLLM | None":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            return None
        return cls(model or DEFAULT_MODEL, key)

    def generate_text(self, prompt: str, *, timeout_s: float | None = None) -> str:
        return self._generate(prompt, timeout_s, None)

    def generate_json(self, prompt: str, schema: dict, *, timeout_s: float | None = None) -> Any:
        from google.genai import types

        config = types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema)
        return _loads(self._generate(prompt, timeout_s, config))

    def _generate(self, prompt: str, timeout_s: float | None, config: Any) -> str:
        from google.genai import errors

        try:
            client = _client(self._api_key, timeout_s)
            response = client.models.generate_content(model=self.model, contents=prompt, config=config)
        except errors.APIError as e:
            if e.code in TRANSIENT_CODES:
                raise LLMUnavailable("rate_limited" if e.code == 429 else f"http_{e.code}") from e
            raise LLMError(f"http_{e.code}") from e
        except Exception as e:
            kind = type(e).__name__
            if isinstance(e, TimeoutError) or "Timeout" in kind:
                raise LLMUnavailable("timeout") from e
            if isinstance(e, (ConnectionError, OSError)) or "Connect" in kind or "Network" in kind:
                raise LLMUnavailable("connection") from e
            raise LLMError(kind) from e

        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise LLMRefused(str(feedback.block_reason))
        text = response.text
        if not text:
            raise LLMBadOutput("empty_response")
        return text
