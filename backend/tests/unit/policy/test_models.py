from __future__ import annotations

import pytest

from rosalind.config import ParserModelSettings, PolicySettings
from rosalind.policy.adapters.llm_ollama import ensure_local
from rosalind.policy.domain.errors import ModelNotAllowedError

MODEL = ParserModelSettings(name="local", model="qwen3.5:9b")


def test_allowlist_resolves_only_configured_models() -> None:
    settings = PolicySettings(models=[MODEL], default_model="local")

    assert settings.resolve_model(None) == MODEL
    assert settings.resolve_model("local") == MODEL
    assert settings.resolve_model("hosted") is None


def test_disabled_model_is_not_resolved() -> None:
    disabled = ParserModelSettings(name="local", model="qwen3.5:9b", enabled=False)
    settings = PolicySettings(models=[disabled], default_model="local")

    assert settings.resolve_model("local") is None


def test_non_loopback_endpoint_is_rejected() -> None:
    with pytest.raises(ModelNotAllowedError):
        ensure_local("https://api.example.com")


def test_loopback_endpoints_are_accepted() -> None:
    ensure_local("http://127.0.0.1:11434")
    ensure_local("http://localhost:11434")
