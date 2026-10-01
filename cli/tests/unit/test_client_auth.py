"""Unit tests for the Keycloak device-flow auth client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from cli.client import auth
from cli.storage.credentials import Credentials, CredentialStore


def _token_payload() -> dict:
    return {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 300,
        "token_type": "Bearer",
    }


def test_start_device_flow_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        auth.httpx,
        "post",
        lambda url, data=None, timeout=None: httpx.Response(
            200,
            json={"device_code": "dc", "user_code": "AAAA", "interval": 5},
            request=httpx.Request("POST", url),
        ),
    )

    result = auth.start_device_flow()

    assert result["device_code"] == "dc"
    assert result["user_code"] == "AAAA"


def test_poll_device_token_succeeds(monkeypatch) -> None:
    def fake_post(url, data=None, timeout=None):
        return httpx.Response(
            200, json=_token_payload(), request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    credentials = auth.poll_device_token("dc", interval=1, timeout=10)

    assert credentials.access_token == "new-access"
    assert credentials.refresh_token == "new-refresh"


def test_poll_device_token_times_out(monkeypatch) -> None:
    def fake_post(url, data=None, timeout=None):
        return httpx.Response(
            400,
            json={"error": "authorization_pending"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(auth.httpx, "post", fake_post)

    with pytest.raises(auth.AuthError):
        auth.poll_device_token("dc", interval=1, timeout=0.01)


def test_get_access_token_none_without_credentials(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials.json")

    assert auth.get_access_token(store) is None


def test_get_access_token_refreshes_expired(tmp_path: Path, monkeypatch) -> None:
    store = CredentialStore(tmp_path / "credentials.json")
    store.save(
        Credentials(
            access_token="expired",
            refresh_token="refresh-token",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    monkeypatch.setattr(
        auth,
        "refresh",
        lambda refresh_token: Credentials(
            access_token="fresh",
            refresh_token="refresh-token",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
    )

    token = auth.get_access_token(store)

    assert token == "fresh"
    saved = store.load()
    assert saved is not None
    assert saved.access_token == "fresh"
