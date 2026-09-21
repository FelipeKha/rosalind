import httpx
import pytest

from cli.client import http


def _fake_request(monkeypatch, status_code=200, response_json=None):
    captured = {}

    def fake(method, url, params=None, json=None, timeout=None):
        captured.update({"method": method, "url": url, "params": params, "json": json})
        payload = response_json if response_json is not None else {}
        return httpx.Response(
            status_code,
            json=payload,
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(http.httpx, "request", fake)
    return captured


def test_get_builds_url(monkeypatch) -> None:
    captured = _fake_request(monkeypatch, response_json={"status": "ok"})

    result = http.api.get("/health")

    assert result == {"status": "ok"}
    assert captured["url"] == "http://localhost:8000/health"


def test_post_sends_json(monkeypatch) -> None:
    captured = _fake_request(monkeypatch, response_json={"import_id": "abc"})

    result = http.api.post("/imports", json={"source_name": "s", "type": "takeout"})

    assert result == {"import_id": "abc"}
    assert captured["json"] == {"source_name": "s", "type": "takeout"}


def test_get_sends_params(monkeypatch) -> None:
    captured = _fake_request(monkeypatch, response_json={"imports": []})

    http.api.get("/people/search", params={"q": "Alex"})

    assert captured["params"] == {"q": "Alex"}


def test_delete_returns_none_on_204(monkeypatch) -> None:
    _fake_request(monkeypatch, status_code=204)

    assert http.api.delete("/imports/abc") is None


def test_error_status_raises_with_detail(monkeypatch) -> None:
    _fake_request(
        monkeypatch, status_code=404, response_json={"detail": "import 1 not found"}
    )

    with pytest.raises(http.ApiClientError) as exc:
        http.api.get("/imports/1")

    assert "import 1 not found" in str(exc.value)


def test_connection_error_raises(monkeypatch) -> None:
    def fake(method, url, params=None, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(http.httpx, "request", fake)

    with pytest.raises(http.ApiClientError):
        http.api.get("/health")


def test_get_health() -> None:
    assert callable(http.get_health)
