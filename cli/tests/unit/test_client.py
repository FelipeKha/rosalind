import httpx
import pytest

from cli import client, config


def test_get_health_returns_status(monkeypatch) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "ok"}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(client.httpx, "get", fake_get)
    assert client.get_health() == {"status": "ok"}


def test_get_health_uses_configured_url(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["timeout"] = timeout
        return httpx.Response(
            200, json={"status": "ok"}, request=httpx.Request("GET", url)
        )

    monkeypatch.setenv("ROSALIND_API_URL", "http://example:9000")
    monkeypatch.setattr(client.httpx, "get", fake_get)

    client.get_health()

    assert captured["url"] == "http://example:9000/health"
    assert captured["timeout"] == client.DEFAULT_TIMEOUT_SECONDS


def test_get_health_uses_default_url(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, timeout: float) -> httpx.Response:
        captured["url"] = url
        return httpx.Response(
            200, json={"status": "ok"}, request=httpx.Request("GET", url)
        )

    monkeypatch.delenv("ROSALIND_API_URL", raising=False)
    monkeypatch.setattr(client.httpx, "get", fake_get)

    client.get_health()

    assert captured["url"] == f"{config.DEFAULT_API_URL}/health"


def test_get_health_raises_on_connection_error(monkeypatch) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(client.httpx, "get", fake_get)

    with pytest.raises(client.ApiClientError):
        client.get_health()


def test_get_health_raises_on_error_status(monkeypatch) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(client.httpx, "get", fake_get)

    with pytest.raises(client.ApiClientError):
        client.get_health()
