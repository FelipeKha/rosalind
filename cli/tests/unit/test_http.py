import httpx
import pytest

from cli.client import auth, http


class _StreamContext:
    """A minimal stand-in for ``httpx.stream``'s context manager."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def __enter__(self) -> httpx.Response:
        return self._response

    def __exit__(self, *exc: object) -> None:
        self._response.close()


def _stream_response(
    status_code: int,
    *,
    body: bytes = b"",
    request: httpx.Request | None = None,
) -> _StreamContext:
    return _StreamContext(
        httpx.Response(
            status_code,
            headers={"content-type": "application/json"},
            stream=httpx.ByteStream(body),
            request=request or httpx.Request("POST", "http://localhost:8000/eval/run"),
        )
    )


def _fake_stream(monkeypatch, status_code=200, body=b""):
    def fake_stream(method, url, **kwargs):
        return _stream_response(
            status_code,
            body=body,
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(http.httpx, "stream", fake_stream)
    monkeypatch.setattr(auth, "get_access_token", lambda *a, **k: None)


def _fake_request(monkeypatch, status_code=200, response_json=None):
    captured = {}

    def fake(method, url, params=None, json=None, headers=None, timeout=None):
        captured.update(
            {
                "method": method,
                "url": url,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
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

    result = http.api.post("/imports", json={"source_name": "s", "via": "file"})

    assert result == {"import_id": "abc"}
    assert captured["json"] == {"source_name": "s", "via": "file"}


def test_post_uses_default_timeout(monkeypatch) -> None:
    captured = _fake_request(monkeypatch)

    http.api.post("/search", json={})

    assert captured["timeout"] == http.DEFAULT_TIMEOUT_SECONDS


def test_post_forwards_explicit_timeout(monkeypatch) -> None:
    captured = _fake_request(monkeypatch)

    http.api.post("/search", json={}, timeout=42.0)

    assert captured["timeout"] == 42.0


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
    def fake(method, url, params=None, json=None, headers=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(http.httpx, "request", fake)

    with pytest.raises(http.ApiClientError):
        http.api.get("/health")


def test_get_health() -> None:
    assert callable(http.get_health)


def test_stream_post_yields_lines(monkeypatch) -> None:
    _fake_stream(monkeypatch, status_code=200, body=b'{"event":"a"}\n{"event":"b"}\n')

    lines = list(http.api.stream_post("/eval/run", json={}))

    assert lines == ['{"event":"a"}', '{"event":"b"}']


def test_stream_post_error_surfaces_detail(monkeypatch) -> None:
    _fake_stream(
        monkeypatch,
        status_code=404,
        body=b'{"detail":"eval mode is disabled"}',
    )

    with pytest.raises(http.ApiClientError) as exc:
        list(http.api.stream_post("/eval/run", json={}))

    assert "eval mode is disabled" in str(exc.value)


def test_stream_post_refreshes_on_401(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_stream(method, url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _stream_response(401, body=b'{"detail":"unauthorized"}')
        return _stream_response(200, body=b'{"event":"ok"}\n')

    monkeypatch.setattr(http.httpx, "stream", fake_stream)
    monkeypatch.setattr(auth, "get_access_token", lambda *a, **k: "token")

    lines = list(http.api.stream_post("/eval/run", json={}))

    assert lines == ['{"event":"ok"}']
    assert calls["count"] == 2
