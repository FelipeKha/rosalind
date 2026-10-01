"""Unit tests for CLI credential storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cli.storage.credentials import Credentials, CredentialStore


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials.json")
    expires = datetime.now(UTC) + timedelta(hours=1)
    store.save(
        Credentials(
            access_token="access",
            refresh_token="refresh",
            expires_at=expires,
        )
    )

    loaded = store.load()

    assert loaded is not None
    assert loaded.access_token == "access"
    assert loaded.refresh_token == "refresh"
    assert loaded.expires_at == expires


def test_load_missing_returns_none(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "nope.json")

    assert store.load() is None


def test_clear_removes_file(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    store = CredentialStore(path)
    store.save(Credentials(access_token="access", refresh_token=None, expires_at=None))
    assert path.exists()

    store.clear()

    assert not path.exists()
