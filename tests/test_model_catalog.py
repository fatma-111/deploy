"""Free-model discovery.

The free tier rotates without notice, so the app must be able to find live
replacements rather than depending on IDs baked into the repo.
"""

import time

import pytest

from app.services import model_catalog
from app.services.llm import LLMService

CATALOG = {
    "data": [
        {  # free, big context, coding provider -> should rank first
            "id": "poolside/laguna-s-2.1:free",
            "name": "Poolside: Laguna S 2.1 (free)",
            "context_length": 262144,
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"context_length": 262144, "max_completion_tokens": 32768},
            "supported_parameters": ["tools", "max_tokens"],
        },
        {  # free but already flagged for removal -> excluded
            "id": "inclusionai/ling-3.0-tiny:free",
            "context_length": 262144,
            "pricing": {"prompt": "0", "completion": "0"},
            "expiration_date": "2020-01-01",
            "top_provider": {"max_completion_tokens": 32768},
        },
        {  # free but context too small for a stack trace + source -> excluded
            "id": "tiny/model:free",
            "context_length": 4096,
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"max_completion_tokens": 1024},
        },
        {  # paid -> excluded
            "id": "anthropic/claude-opus-5",
            "context_length": 1000000,
            "pricing": {"prompt": "0.000005", "completion": "0.000025"},
            "top_provider": {"max_completion_tokens": 128000},
        },
        {  # free, generic provider -> included, ranked after the coding model
            "id": "liquid/lfm-2.5-2.6b:free",
            "context_length": 128000,
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"max_completion_tokens": 32768},
        },
    ]
}


@pytest.fixture
def catalog(monkeypatch):
    model_catalog._cache.update({"fetched_at": 0.0, "models": []})
    monkeypatch.setattr(model_catalog, "fetch_json", lambda *a, **k: CATALOG)
    monkeypatch.setattr("app.config.settings.settings.model_discovery_enabled_raw", True)
    yield
    model_catalog._cache.update({"fetched_at": 0.0, "models": []})


def test_only_usable_free_models_are_kept(catalog):
    ids = [m.id for m in model_catalog.fetch_free_models(force=True)]
    assert "poolside/laguna-s-2.1:free" in ids
    assert "liquid/lfm-2.5-2.6b:free" in ids
    assert "anthropic/claude-opus-5" not in ids       # paid
    assert "inclusionai/ling-3.0-tiny:free" not in ids  # expiring
    assert "tiny/model:free" not in ids                # context too small


def test_coding_models_rank_first(catalog):
    assert model_catalog.fetch_free_models(force=True)[0].id == "poolside/laguna-s-2.1:free"


def test_results_are_cached(catalog, monkeypatch):
    model_catalog.fetch_free_models(force=True)
    calls = []
    monkeypatch.setattr(
        model_catalog, "fetch_json", lambda *a, **k: calls.append(1) or CATALOG
    )
    model_catalog.fetch_free_models()
    assert not calls, "a cached catalog must not re-fetch"


def test_unreachable_catalog_returns_empty_not_an_error(monkeypatch):
    model_catalog._cache.update({"fetched_at": 0.0, "models": []})
    monkeypatch.setattr(model_catalog, "fetch_json", lambda *a, **k: None)
    assert model_catalog.fetch_free_models(force=True) == []


def test_discovered_models_extend_the_fallback_chain(catalog, monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.openrouter_model", "primary/model")
    monkeypatch.setattr(
        "app.config.settings.settings.openrouter_fallback_models_raw", "backup/model"
    )
    chain = LLMService()._model_chain(prefer_fast=False)
    assert chain[:2] == ["primary/model", "backup/model"]
    assert "poolside/laguna-s-2.1:free" in chain


def test_discovery_can_be_switched_off(catalog, monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.model_discovery_enabled_raw", False)
    monkeypatch.setattr("app.config.settings.settings.openrouter_model", "primary/model")
    monkeypatch.setattr("app.config.settings.settings.openrouter_fallback_models_raw", "")
    assert LLMService()._model_chain(prefer_fast=False) == ["primary/model"]


def test_dead_model_error_is_actionable():
    assert LLMService._is_missing_model(Exception("Error code: 404 - No endpoints found"))
    assert not LLMService._is_missing_model(Exception("429 rate limit exceeded"))


def test_llm_vars_override_the_openrouter_defaults(monkeypatch):
    """Switching provider is configuration, not code."""
    from app.config.settings import Settings

    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
    settings = Settings()

    assert settings.provider_name == "openai"
    assert settings.openrouter_base_url == "https://api.openai.com/v1"
    assert settings.openrouter_api_key == "sk-test-key"
    # OpenAI publishes no free catalog, so discovery must not run against it.
    assert settings.model_discovery_enabled is False


def test_openrouter_remains_the_default(monkeypatch):
    from app.config.settings import Settings

    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings = Settings()
    assert settings.provider_name == "openrouter"
    assert settings.model_discovery_enabled is True
