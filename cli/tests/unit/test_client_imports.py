from cli.client import imports as imports_client


class FakeApi:
    def __init__(self, response=None):
        self.calls = []
        self.response = response

    def post(self, path, *, json=None):
        self.calls.append(("post", path, json))
        return self.response or {}

    def get(self, path, *, params=None):
        self.calls.append(("get", path, params))
        return self.response or {"imports": []}

    def delete(self, path):
        self.calls.append(("delete", path))


def _stub(monkeypatch, response=None):
    fake = FakeApi(response=response)
    monkeypatch.setattr(imports_client.http, "api", fake)
    return fake


def test_create_import_posts_source_and_type(monkeypatch) -> None:
    fake = _stub(monkeypatch)

    imports_client.create_import("google-personal", "takeout")

    assert fake.calls == [
        ("post", "/imports", {"source_name": "google-personal", "type": "takeout"})
    ]


def test_complete_import_posts_manifest(monkeypatch) -> None:
    fake = _stub(monkeypatch)
    manifest: dict[str, object] = {"files": []}

    imports_client.complete_import("import-1", manifest)

    assert fake.calls == [("post", "/imports/import-1/complete", manifest)]


def test_list_imports_returns_items(monkeypatch) -> None:
    fake = _stub(monkeypatch, response={"imports": [{"import_id": "abc"}]})

    result = imports_client.list_imports()

    assert result == [{"import_id": "abc"}]
    assert fake.calls == [("get", "/imports", None)]


def test_get_import_returns_detail(monkeypatch) -> None:
    fake = _stub(monkeypatch, response={"import_id": "abc"})

    result = imports_client.get_import("abc")

    assert result == {"import_id": "abc"}
    assert fake.calls == [("get", "/imports/abc", None)]


def test_delete_import_uses_delete(monkeypatch) -> None:
    fake = _stub(monkeypatch)

    imports_client.delete_import("abc")

    assert fake.calls == [("delete", "/imports/abc")]
