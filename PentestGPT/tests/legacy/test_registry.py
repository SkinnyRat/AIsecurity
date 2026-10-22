"""Tests for the supported-model registry."""

import pytest

from pentestgpt_legacy.llm.registry import (
    MODELS,
    PROVIDERS,
    all_model_ids,
    models_by_provider,
    resolve,
)

pytestmark = pytest.mark.unit


def test_resolve_known_model() -> None:
    spec = resolve("gpt-5.5")
    assert spec is not None
    assert spec.provider == "openai"
    assert spec.api_id == "gpt-5.5"  # api_id defaults to id


def test_resolve_alias() -> None:
    spec = resolve("claude-haiku-4-5")
    assert spec is not None
    assert spec.id == "claude-haiku-4-5-20251001"


def test_resolve_ollama_dynamic() -> None:
    spec = resolve("ollama:qwen3")
    assert spec is not None
    assert spec.provider == "ollama"
    assert spec.api_id == "qwen3"


def test_resolve_ollama_empty_is_none() -> None:
    assert resolve("ollama:") is None


def test_resolve_unknown_is_none() -> None:
    assert resolve("definitely-not-a-model") is None


def test_all_model_ids_unique_and_nonempty() -> None:
    ids = all_model_ids()
    assert ids
    assert len(ids) == len(set(ids))


def test_every_model_provider_is_registered() -> None:
    for spec in MODELS.values():
        assert spec.provider in PROVIDERS


def test_api_id_defaults_to_id() -> None:
    for spec in MODELS.values():
        assert spec.api_id  # never empty


def test_models_by_provider_covers_all() -> None:
    grouped = models_by_provider()
    total = sum(len(specs) for specs in grouped.values())
    assert total == len(MODELS)
    # current flagship providers must be present
    for provider in ("openai", "anthropic", "gemini", "deepseek"):
        assert provider in grouped
