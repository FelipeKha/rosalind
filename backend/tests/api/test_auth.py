"""API tests for bearer-token authentication."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_requires_bearer_token(auth_api_client: TestClient) -> None:
    response = auth_api_client.get("/sources")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_rejects_invalid_token(auth_api_client: TestClient) -> None:
    response = auth_api_client.get("/sources", headers={"Authorization": "Bearer bad"})

    assert response.status_code == 401


def test_accepts_valid_token(auth_api_client: TestClient) -> None:
    response = auth_api_client.get("/sources", headers={"Authorization": "Bearer good"})

    assert response.status_code == 200


def test_health_is_unprotected(auth_api_client: TestClient) -> None:
    response = auth_api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
