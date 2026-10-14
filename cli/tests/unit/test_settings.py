"""Unit tests for CLI settings resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cli import config, settings
from cli.storage.credentials import credentials_path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("ROSALIND_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ROSALIND_CONFIG_DIR", str(tmp_path))


def _write(path: Path, text: str) -> None:
    path.write_text(text)


def test_defaults_when_no_config_file() -> None:
    resolved = settings.get_settings()

    assert resolved.api_url == "http://localhost:8000"
    assert resolved.keycloak_url == "http://localhost:8080"
    assert resolved.s3_endpoint == "http://localhost:8333"


def test_base_yaml_overrides_defaults(tmp_path: Path) -> None:
    _write(
        tmp_path / "rosalind.yaml",
        "api_url: http://localhost:9000\nkeycloak_url: http://localhost:9999\n",
    )

    resolved = settings.get_settings()

    assert resolved.api_url == "http://localhost:9000"
    assert resolved.keycloak_url == "http://localhost:9999"
    assert resolved.s3_endpoint == "http://localhost:8333"


def test_profile_layers_on_top_of_base(tmp_path: Path) -> None:
    _write(tmp_path / "rosalind.yaml", "api_url: http://base:8000\ns3_bucket: base\n")
    _write(tmp_path / "eval.yaml", "api_url: http://eval:8001\n")
    os.environ["ROSALIND_PROFILE"] = "eval"

    resolved = settings.get_settings()

    assert resolved.api_url == "http://eval:8001"
    assert resolved.s3_bucket == "base"


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path / "rosalind.yaml", "api_url: http://from-yaml:8000\n")
    monkeypatch.setenv("ROSALIND_API_URL", "http://from-env:8001")

    assert settings.get_settings().api_url == "http://from-env:8001"


def test_config_env_var_selects_file(tmp_path: Path) -> None:
    explicit = tmp_path / "custom.yaml"
    _write(explicit, "api_url: http://custom:8000\n")
    os.environ["ROSALIND_CONFIG"] = str(explicit)

    assert settings.get_settings().api_url == "http://custom:8000"


def test_non_mapping_config_raises(tmp_path: Path) -> None:
    _write(tmp_path / "rosalind.yaml", "- not\n- a\n- mapping\n")

    with pytest.raises(ValueError, match="must be a mapping"):
        settings.get_settings()


def test_missing_profile_raises(tmp_path: Path) -> None:
    os.environ["ROSALIND_PROFILE"] = "eval"

    with pytest.raises(ValueError, match="profile config not found"):
        settings.get_settings()


def test_config_accessor_delegates_to_settings(tmp_path: Path) -> None:
    _write(tmp_path / "rosalind.yaml", "api_url: http://delegated:8001\n")

    assert config.api_url() == "http://delegated:8001"


def test_credentials_path_default(tmp_path: Path) -> None:
    assert credentials_path() == tmp_path / "credentials.json"


def test_credentials_path_per_profile(tmp_path: Path) -> None:
    os.environ["ROSALIND_PROFILE"] = "eval"

    assert credentials_path() == tmp_path / "eval" / "credentials.json"


def test_xdg_config_home_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ROSALIND_CONFIG_DIR", raising=False)
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    assert credentials_path() == xdg / "rosalind" / "credentials.json"
