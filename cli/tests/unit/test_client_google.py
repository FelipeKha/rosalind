import httpx
import pytest

from cli import client


def test_connect_google_posts_to_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, timeout: float) -> httpx.Response:
        captured["url"] = url
        return httpx.Response(
            200,
            json={"auth_url": "https://example.com", "state": "s1"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(client.httpx, "post", fake_post)

    result = client.connect_google()

    assert result == {"auth_url": "https://example.com", "state": "s1"}
    assert captured["url"] == "http://localhost:8000/auth/google/connect"


def test_google_auth_status_passes_state(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, params: object, timeout: float) -> httpx.Response:
        captured["params"] = params
        return httpx.Response(
            200, json={"status": "pending"}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(client.httpx, "get", fake_get)

    result = client.google_auth_status("state-1")

    assert result == {"status": "pending"}
    assert captured["params"] == {"state": "state-1"}


def test_import_google_profile_posts_to_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, timeout: float) -> httpx.Response:
        captured["url"] = url
        return httpx.Response(
            200,
            json={"status": "success", "display_name": "Jane"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(client.httpx, "post", fake_post)

    result = client.import_google_profile()

    assert result == {"status": "success", "display_name": "Jane"}
    assert captured["url"] == "http://localhost:8000/imports/google/profile"


def test_connect_google_raises_on_error(monkeypatch) -> None:
    def fake_post(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(client.httpx, "post", fake_post)

    with pytest.raises(client.ApiClientError):
        client.connect_google()
