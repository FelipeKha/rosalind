"""CLI configuration loaded from environment variables and an optional YAML file.

Precedence: environment variables > YAML file > defaults. The YAML file is named
by ``ROSALIND_CONFIG`` (default ``<config_dir>/rosalind.yaml``, where
``config_dir`` is ``ROSALIND_CONFIG_DIR`` or ``~/.config/rosalind``). A profile
selected with ``ROSALIND_PROFILE`` (or ``--profile``) layers
``<config_dir>/<profile>.yaml`` on top of the base file. Missing files are not
an error; a selected profile whose file is missing is.

This mirrors the backend's configuration approach (see
``backend/src/rosalind/config.py``) so both sides read YAML the same way.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def config_dir() -> Path:
    """Directory holding the CLI config file(s) and stored credentials."""
    override = os.environ.get("ROSALIND_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path("~/.config").expanduser()
    return base / "rosalind"


def profile() -> str | None:
    """The selected config profile, if any."""
    return os.environ.get("ROSALIND_PROFILE", "").strip() or None


def config_file_path() -> Path:
    """Path to the base config file (``ROSALIND_CONFIG`` overrides it)."""
    override = os.environ.get("ROSALIND_CONFIG")
    if override:
        return Path(override).expanduser()
    return config_dir() / "rosalind.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text())
    if loaded is None:
        return {}
    if isinstance(loaded, dict):
        return loaded
    raise ValueError(f"config file must be a mapping: {path}")


class CliYamlSettingsSource(PydanticBaseSettingsSource):
    """Load settings from the base YAML file and the selected profile."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        data = _load_yaml(config_file_path())
        selected = profile()
        if selected:
            profile_path = config_dir() / f"{selected}.yaml"
            if not profile_path.is_file():
                raise ValueError(f"profile config not found: {profile_path}")
            data = {**data, **_load_yaml(profile_path)}
        self._data = data

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data


class CliSettings(BaseSettings):
    """Resolved CLI settings. Environment variables override the YAML file."""

    model_config = SettingsConfigDict(env_prefix="ROSALIND_")

    api_url: str = "http://localhost:8000"
    search_timeout: float = 60.0
    s3_endpoint: str = "http://localhost:8333"
    s3_access_key: str = "rosalind"
    s3_secret_key: str = "rosalind"  # nosec B105 - local dev default
    s3_bucket: str = "rosalind"
    s3_region: str = "us-east-1"
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "rosalind"
    keycloak_client_id: str = "rosalind-cli"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            CliYamlSettingsSource(settings_cls),
            file_secret_settings,
        )


def get_settings() -> CliSettings:
    """Resolve settings from the current environment and config files."""
    return CliSettings()
