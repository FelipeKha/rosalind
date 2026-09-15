import httpx
import pytest

from cli import client


def test_create_import_posts_to_provider_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, timeout: float) -> httpx.Response:
        captured["url"] = url
        return httpx.Response(
            200, json={"import_id": "abc"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(client.httpx, "post", fake_post)

    result = client.create_import("google", "takeout")

    assert result == {"import_id": "abc"}
    assert captured["url"] == "http://localhost:8000/imports/google/takeout"


def test_complete_import_posts_manifest(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, json: object, timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(
            200, json={"status": "completed"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(client.httpx, "post", fake_post)

    manifest: dict[str, object] = {"files": []}
    result = client.complete_import("import-1", manifest)

    assert result == {"status": "completed"}
    assert captured["url"] == "http://localhost:8000/imports/import-1/complete"
    assert captured["json"] == manifest


def test_create_import_raises_on_error(monkeypatch) -> None:
    def fake_post(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(client.httpx, "post", fake_post)

    with pytest.raises(client.ApiClientError):
        client.create_import("google", "takeout")


def test_list_imports_returns_items(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, timeout: float) -> httpx.Response:
        captured["url"] = url
        return httpx.Response(
            200,
            json={"imports": [{"import_id": "abc"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(client.httpx, "get", fake_get)

    result = client.list_imports()

    assert result == [{"import_id": "abc"}]
    assert captured["url"] == "http://localhost:8000/imports"


def test_get_import_returns_detail(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, timeout: float) -> httpx.Response:
        captured["url"] = url
        return httpx.Response(
            200,
            json={"import_id": "abc"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(client.httpx, "get", fake_get)

    result = client.get_import("abc")

    assert result == {"import_id": "abc"}
    assert captured["url"] == "http://localhost:8000/imports/abc"


def test_delete_import_uses_delete(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_delete(url: str, timeout: float) -> httpx.Response:
        captured["url"] = url
        return httpx.Response(204, request=httpx.Request("DELETE", url))

    monkeypatch.setattr(client.httpx, "delete", fake_delete)

    client.delete_import("abc")

    assert captured["url"] == "http://localhost:8000/imports/abc"


def test_delete_import_raises_on_error(monkeypatch) -> None:
    def fake_delete(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(client.httpx, "delete", fake_delete)

    with pytest.raises(client.ApiClientError):
        client.delete_import("abc")
