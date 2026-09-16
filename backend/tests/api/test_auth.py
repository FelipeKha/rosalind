from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from google.oauth2.credentials import Credentials

from rosalind.auth import service as auth_service
from rosalind.providers.google import people as google_people

FAKE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth?foo=bar"


def _fake_credentials() -> Credentials:
    return Credentials(
        token="access-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        expiry=datetime.now(UTC) + timedelta(hours=1),
    )


def _stub_google(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_service.google_auth, "build_authorization_url", lambda state: FAKE_AUTH_URL
    )
    monkeypatch.setattr(
        auth_service.google_auth,
        "exchange_code",
        lambda state, code: _fake_credentials(),
    )
    monkeypatch.setattr(
        auth_service.google_auth,
        "fetch_userinfo",
        lambda credentials: {
            "id": "12345",
            "email": "jane@example.com",
            "name": "Jane Doe",
        },
    )


def _connect(api_client: TestClient) -> dict[str, str]:
    response = api_client.post("/auth/google/connect")
    assert response.status_code == 200
    return response.json()


def test_connect_returns_auth_url_and_state(
    api_client: TestClient, monkeypatch
) -> None:
    _stub_google(monkeypatch)

    body = _connect(api_client)
    assert body["auth_url"] == FAKE_AUTH_URL
    assert body["state"]


def test_auth_status_pending_before_callback(
    api_client: TestClient, monkeypatch
) -> None:
    _stub_google(monkeypatch)

    body = _connect(api_client)
    response = api_client.get("/auth/google/status", params={"state": body["state"]})
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_callback_completes_flow(api_client: TestClient, monkeypatch) -> None:
    _stub_google(monkeypatch)

    body = _connect(api_client)
    state = body["state"]

    response = api_client.get(
        "/auth/google/callback", params={"state": state, "code": "auth-code"}
    )
    assert response.status_code == 200

    status = api_client.get("/auth/google/status", params={"state": state})
    body = status.json()
    assert body["status"] == "connected"
    assert body["display_name"] == "Jane Doe"
    assert body["source_account_id"] is not None


def test_callback_rejects_unknown_state(api_client: TestClient) -> None:
    response = api_client.get(
        "/auth/google/callback", params={"state": "unknown", "code": "auth-code"}
    )
    assert response.status_code == 400


def test_import_profile_returns_confirmation(
    api_client: TestClient, monkeypatch
) -> None:
    _stub_google(monkeypatch)
    monkeypatch.setattr(
        google_people,
        "fetch_profile",
        lambda credentials: {
            "resourceName": "people/12345",
            "names": [{"displayName": "Jane Doe"}],
        },
    )

    state = _connect(api_client)["state"]
    api_client.get(
        "/auth/google/callback", params={"state": state, "code": "auth-code"}
    )

    response = api_client.post("/imports/google/profile")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["account"] == "12345"
    assert body["display_name"] == "Jane Doe"
    assert body["fetched_at"]


def test_import_profile_requires_credentials(api_client: TestClient) -> None:
    response = api_client.post("/imports/google/profile")
    assert response.status_code == 409
