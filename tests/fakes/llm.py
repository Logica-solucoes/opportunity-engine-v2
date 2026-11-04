"""Test doubles for the llm module, and the contract every provider adapter must satisfy."""

import json
from collections.abc import Callable
from typing import Any

import pytest

from llm.base import LLMBadOutput, LLMUnavailable

TRANSIENT = object()  # a reply that makes the provider fail the way an outage does


class FakeLLM:
    provider = "fake"
    model = "fake"

    def __init__(self, replies: list[Any]):
        self.replies = list(replies)
        self.calls: list[str] = []
        self.timeouts: list[float | None] = []

    def _next(self, prompt: str, timeout_s: float | None) -> str:
        self.calls.append(prompt)
        self.timeouts.append(timeout_s)
        reply = self.replies.pop(0)
        if reply is TRANSIENT:
            raise LLMUnavailable("transient")
        if isinstance(reply, Exception):
            raise reply
        return reply

    def generate_text(self, prompt: str, *, timeout_s: float | None = None) -> str:
        return self._next(prompt, timeout_s)

    def generate_json(self, prompt: str, schema: dict, *, timeout_s: float | None = None) -> Any:
        text = self._next(prompt, timeout_s)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMBadOutput("invalid_json") from e


def run_provider_contract(make: Callable[[list[Any]], Any]) -> None:
    """`make(replies)` builds a provider whose successive calls yield the replies (str, or TRANSIENT)."""
    assert make(["hello"]).generate_text("p") == "hello"
    assert make(['{"a": 1}']).generate_json("p", {"type": "object"}) == {"a": 1}
    with pytest.raises(LLMBadOutput):
        make(["not json"]).generate_json("p", {"type": "object"})
    with pytest.raises(LLMUnavailable) as raised:
        make([TRANSIENT]).generate_text("p")
    assert str(raised.value) == raised.value.reason and raised.value.reason
