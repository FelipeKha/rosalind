"""API tests for the current-account profile endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_me_requires_auth(auth_api_client: TestClient) -> None:
    response = auth_api_client.get("/me")

    assert response.status_code == 401


def test_me_returns_profile(auth_api_client: TestClient) -> None:
    response = auth_api_client.get("/me", headers={"Authorization": "Bearer good"})

    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "user-test"
    assert body["email"] == "jane@example.com"
    assert body["given_name"] == "Jane"
    assert body["family_name"] == "Doe"
    assert body["account_id"]
