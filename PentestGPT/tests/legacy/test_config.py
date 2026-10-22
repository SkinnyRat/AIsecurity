"""Tests for provider credential/base-url resolution."""

import pytest

from pentestgpt_legacy.llm import config as config_mod
from pentestgpt_legacy.llm.config import LLMSettings, configured_providers
from pentestgpt_legacy.llm.registry import PROVIDERS

pytestmark = pytest.mark.unit


def test_api_key_for_primary_field() -> None:
    settings = LLMSettings(_env_file=None, openai_api_key="sk-openai")
    assert settings.api_key_for(PROVIDERS["openai"]) == "sk-openai"


def test_api_key_for_alias_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")
    settings = LLMSettings(_env_file=None)
    assert settings.api_key_for(PROVIDERS["gemini"]) == "g-key"


def test_ollama_needs_no_key() -> None:
    settings = LLMSettings(_env_file=None)
    assert settings.api_key_for(PROVIDERS["ollama"]) is None
    assert PROVIDERS["ollama"].requires_key is False


def test_base_url_default_and_override() -> None:
    settings = LLMSettings(_env_file=None)
    assert settings.base_url_for(PROVIDERS["deepseek"]) == "https://api.deepseek.com"
    # OpenAI default is the SDK default (None)
    assert settings.base_url_for(PROVIDERS["openai"]) is None

    overridden = LLMSettings(_env_file=None, deepseek_base_url="http://localhost:9/v1")
    assert overridden.base_url_for(PROVIDERS["deepseek"]) == "http://localhost:9/v1"


def test_configured_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = LLMSettings(_env_file=None, openai_api_key="x")
    monkeypatch.setattr(config_mod, "_settings", fake)
    ready = configured_providers()
    assert "openai" in ready
    assert "ollama" in ready  # needs no key
    assert "anthropic" not in ready
