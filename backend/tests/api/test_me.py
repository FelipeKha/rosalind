"""API tests for the current-account profile endpoint."""

from __future__ import annotations

import uuid

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


def test_set_self_person_requires_email(auth_api_client: TestClient) -> None:
    response = auth_api_client.put(
        "/me/self-person",
        json={"person_id": str(uuid.uuid4())},
        headers={"Authorization": "Bearer good"},
    )

    assert response.status_code == 422
    assert "no email" in response.json()["detail"]
