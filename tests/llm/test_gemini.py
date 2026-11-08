from types import SimpleNamespace

import pytest
from google.genai import errors

import llm.gemini as gemini_module
from llm.base import LLMBadOutput, LLMError, LLMRefused, LLMUnavailable
from llm.gemini import GeminiLLM
from tests.fakes.llm import TRANSIENT, run_provider_contract


class FakeGenaiClient:
    """Stands in for google.genai.Client: replies are text or an exception to raise."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.models = self

    def generate_content(self, model, contents, config=None):
        self.requests.append({"model": model, "contents": contents, "config": config})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, SimpleNamespace):
            return reply
        return SimpleNamespace(text=reply, prompt_feedback=None)


@pytest.fixture
def install(monkeypatch):
    def _install(replies):
        client = FakeGenaiClient(replies)
        seen = []
        monkeypatch.setattr(
            gemini_module, "_client", lambda api_key, timeout_s: seen.append((api_key, timeout_s)) or client
        )
        return GeminiLLM("gemini-test", "key"), client, seen

    return _install


def test_generate_text_returns_text_and_passes_model_and_timeout(install):
    llm, client, seen = install(["olá"])
    assert llm.generate_text("prompt", timeout_s=60) == "olá"
    assert client.requests[0]["model"] == "gemini-test" and client.requests[0]["contents"] == "prompt"
    assert seen == [("key", 60)]


def test_generate_json_parses_and_strips_code_fence(install):
    llm, client, _ = install(['```json\n{"a": [1, 2]}\n```'])
    assert llm.generate_json("p", {"type": "object"}) == {"a": [1, 2]}
    config = client.requests[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == {"type": "object"}
    assert config.temperature == 0  # structured output is meant to be reproducible (A9)


@pytest.mark.parametrize("code", [429, 500, 503, 504])
def test_transient_http_errors_map_to_unavailable(install, code):
    llm, _, _ = install([errors.APIError(code, {"error": {"message": "x"}})])
    with pytest.raises(LLMUnavailable) as raised:
        llm.generate_text("p")
    assert str(code) in raised.value.reason or raised.value.reason == "rate_limited"


def test_400_is_a_plain_llm_error(install):
    llm, _, _ = install([errors.APIError(400, {"error": {"message": "bad"}})])
    with pytest.raises(LLMError) as raised:
        llm.generate_text("p")
    assert not isinstance(raised.value, LLMUnavailable)


def test_timeout_and_connection_failures_are_unavailable(install):
    llm, _, _ = install([TimeoutError(), ConnectionError()])
    for expected in ("timeout", "connection"):
        with pytest.raises(LLMUnavailable) as raised:
            llm.generate_text("p")
        assert raised.value.reason == expected


def test_empty_text_is_bad_output(install):
    llm, _, _ = install([SimpleNamespace(text=None, prompt_feedback=None)])
    with pytest.raises(LLMBadOutput):
        llm.generate_text("p")


def test_blocked_prompt_is_refused(install):
    llm, _, _ = install([SimpleNamespace(text=None, prompt_feedback=SimpleNamespace(block_reason="SAFETY"))])
    with pytest.raises(LLMRefused):
        llm.generate_text("p")


def test_gemini_passes_the_provider_contract(install):
    def make(replies):
        mapped = [errors.APIError(503, {}) if r is TRANSIENT else r for r in replies]
        return install(mapped)[0]

    run_provider_contract(make)
