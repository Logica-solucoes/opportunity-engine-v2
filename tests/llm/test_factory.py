import pytest

from llm import PROVIDERS, get_llm


def test_none_provider_returns_none(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert get_llm() is None


def test_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert get_llm() is None


def test_unknown_provider_raises_value_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="nope"):
        get_llm()


def test_model_and_provider_come_from_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "gemini-test")
    llm = get_llm()
    assert (llm.provider, llm.model) == ("gemini", "gemini-test")


def test_default_model_is_the_flash_alias(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert get_llm().model == "gemini-flash-latest"


def test_registry_lists_gemini_only():
    assert set(PROVIDERS) == {"gemini"}
