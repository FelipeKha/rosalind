"""Local credential storage for the CLI.

Stores the Keycloak-issued tokens on disk so the CLI can authenticate backend
requests without re-prompting. The file is written with owner-only permissions;
tokens are never logged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Credentials:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    token_type: str = "Bearer"


def credentials_path() -> Path:
    base = os.environ.get(
        "ROSALIND_CONFIG_DIR", os.environ.get("XDG_CONFIG_HOME", "~/.config")
    )
    return Path(base).expanduser() / "rosalind" / "credentials.json"


class CredentialStore:
    def __init__(self, path: Path | None = None):
        self._path = path or credentials_path()

    def load(self) -> Credentials | None:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError, json.JSONDecodeError, OSError:
            return None

        expires_at = raw.get("expires_at")
        return Credentials(
            access_token=raw.get("access_token", ""),
            refresh_token=raw.get("refresh_token"),
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            token_type=raw.get("token_type", "Bearer"),
        )

    def save(self, credentials: Credentials) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": credentials.access_token,
            "refresh_token": credentials.refresh_token,
            "expires_at": (
                credentials.expires_at.isoformat() if credentials.expires_at else None
            ),
            "token_type": credentials.token_type,
        }
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle)
        finally:
            pass

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
