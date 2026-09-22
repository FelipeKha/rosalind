from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from rosalind.adapters import composition
from rosalind.application.errors import ProviderError
from rosalind.application.ports.providers import ProviderCredentials, UserIdentity

FAKE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth?foo=bar"


def _fake_credentials() -> ProviderCredentials:
    return ProviderCredentials(
        access_token="access-token",
        refresh_token="refresh-token",
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _stub_google(monkeypatch) -> None:
    monkeypatch.setattr(
        composition.google_auth,
        "build_authorization_url",
        lambda state: (FAKE_AUTH_URL, "code-verifier"),
    )
    monkeypatch.setattr(
        composition.google_auth,
        "exchange_code",
        lambda state, code, code_verifier: _fake_credentials(),
    )
    monkeypatch.setattr(
        composition.google_auth,
        "fetch_userinfo",
        lambda credentials: UserIdentity(
            account_identifier="12345", display_name="Jane Doe"
        ),
    )


def _connect(api_client: TestClient) -> dict[str, str]:
    response = api_client.post(
        "/sources/connect", json={"provider": "google", "name": "google-personal"}
    )
    assert response.status_code == 200
    return response.json()


def test_create_source(api_client: TestClient) -> None:
    response = api_client.post(
        "/sources", json={"provider": "google", "name": "google-personal"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "google-personal"
    assert body["provider"] == "google"
    assert body["status"] == "disconnected"


def test_list_sources(api_client: TestClient) -> None:
    api_client.post("/sources", json={"provider": "google", "name": "google-personal"})

    response = api_client.get("/sources")
    assert response.status_code == 200
    assert [s["name"] for s in response.json()["sources"]] == ["google-personal"]


def test_connect_returns_auth_url_and_state(
    api_client: TestClient, monkeypatch
) -> None:
    _stub_google(monkeypatch)

    body = _connect(api_client)
    assert body["auth_url"] == FAKE_AUTH_URL
    assert body["state"]
    assert body["source_id"]


def test_auth_status_pending_before_callback(
    api_client: TestClient, monkeypatch
) -> None:
    _stub_google(monkeypatch)

    body = _connect(api_client)
    response = api_client.get(
        "/sources/connect/status", params={"state": body["state"]}
    )
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

    status = api_client.get("/sources/connect/status", params={"state": state})
    body = status.json()
    assert body["status"] == "connected"
    assert body["display_name"] == "Jane Doe"
    assert body["source_id"] is not None


def test_callback_rejects_unknown_state(api_client: TestClient) -> None:
    response = api_client.get(
        "/auth/google/callback", params={"state": "unknown", "code": "auth-code"}
    )
    assert response.status_code == 400


def test_api_import_creates_canonical_data(
    migrated_api_client: TestClient, monkeypatch
) -> None:
    _stub_google(monkeypatch)
    monkeypatch.setattr(
        composition.google_people,
        "fetch_profile",
        lambda credentials: {
            "resourceName": "people/12345",
            "names": [
                {
                    "displayName": "Jane Doe",
                    "givenName": "Jane",
                    "familyName": "Doe",
                }
            ],
            "emailAddresses": [
                {"value": "jane@example.com", "metadata": {"primary": True}}
            ],
        },
    )

    state = _connect(migrated_api_client)["state"]
    migrated_api_client.get(
        "/auth/google/callback", params={"state": state, "code": "auth-code"}
    )

    response = migrated_api_client.post(
        "/imports", json={"source_name": "google-personal", "type": "api"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "api"
    assert body["ingestion_status"] == "completed"
    assert body["processing_status"] == "completed"

    people = migrated_api_client.get("/people/search", params={"q": "Jane"})
    assert people.status_code == 200
    assert people.json()[0]["display_name"] == "Jane Doe"


def test_api_import_requires_credentials(api_client: TestClient) -> None:
    api_client.post("/sources", json={"provider": "google", "name": "google-personal"})
    response = api_client.post(
        "/imports", json={"source_name": "google-personal", "type": "api"}
    )
    assert response.status_code == 409


def test_disconnect_removes_credentials(api_client: TestClient, monkeypatch) -> None:
    _stub_google(monkeypatch)
    revoke_calls: list[str] = []
    monkeypatch.setattr(
        composition.google_auth, "revoke", lambda token: revoke_calls.append(token)
    )

    body = _connect(api_client)
    api_client.get(
        "/auth/google/callback", params={"state": body["state"], "code": "auth-code"}
    )

    response = api_client.post(f"/sources/{body['source_id']}/disconnect")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "disconnected"
    assert result["revoked"] is True
    assert revoke_calls == ["refresh-token"]

    api_client.post(
        "/sources", json={"provider": "google", "name": "google-personal-2"}
    )
    assert (
        api_client.post(
            "/imports", json={"source_name": "google-personal-2", "type": "api"}
        ).status_code
        == 409
    )


def test_disconnect_revocation_failure_still_removes(
    api_client: TestClient, monkeypatch
) -> None:
    _stub_google(monkeypatch)

    def boom(token: str) -> None:
        raise ProviderError("network down")

    monkeypatch.setattr(composition.google_auth, "revoke", boom)

    body = _connect(api_client)
    api_client.get(
        "/auth/google/callback", params={"state": body["state"], "code": "auth-code"}
    )

    response = api_client.post(f"/sources/{body['source_id']}/disconnect")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "disconnected"
    assert result["revoked"] is False


def test_disconnect_already_disconnected(api_client: TestClient, monkeypatch) -> None:
    _stub_google(monkeypatch)

    created = api_client.post(
        "/sources", json={"provider": "google", "name": "google-personal"}
    ).json()
    response = api_client.post(f"/sources/{created['source_id']}/disconnect")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "already_disconnected"
    assert body["revoked"] is False


def test_reconnect_reuses_account(api_client: TestClient, monkeypatch) -> None:
    _stub_google(monkeypatch)
    monkeypatch.setattr(composition.google_auth, "revoke", lambda token: None)

    first_state = _connect(api_client)["state"]
    api_client.get(
        "/auth/google/callback", params={"state": first_state, "code": "auth-code"}
    )
    first_source_id = api_client.get(
        "/sources/connect/status", params={"state": first_state}
    ).json()["source_id"]

    api_client.post(f"/sources/{first_source_id}/disconnect")

    second_state = _connect(api_client)["state"]
    api_client.get(
        "/auth/google/callback", params={"state": second_state, "code": "auth-code"}
    )

    status = api_client.get("/sources/connect/status", params={"state": second_state})
    body = status.json()
    assert body["status"] == "connected"
    assert body["source_id"] == first_source_id
