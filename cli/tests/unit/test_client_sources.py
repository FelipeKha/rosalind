from cli.client import processing, query, sources


class FakeApi:
    def __init__(self):
        self.calls = []

    def post(self, path, *, json=None):
        self.calls.append(("post", path, json))
        return {}

    def get(self, path, *, params=None):
        self.calls.append(("get", path, params))
        return {"sources": []}


def test_list_sources(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(sources.http, "api", fake)

    sources.list_sources()

    assert fake.calls == [("get", "/sources", None)]


def test_create_source(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(sources.http, "api", fake)

    sources.create_source("google", "google-personal")

    assert fake.calls == [
        ("post", "/sources", {"provider": "google", "name": "google-personal"})
    ]


def test_connect(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(sources.http, "api", fake)

    sources.connect("google", "google-personal")

    assert fake.calls == [
        ("post", "/sources/connect", {"provider": "google", "name": "google-personal"})
    ]


def test_connect_status(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(sources.http, "api", fake)

    sources.connect_status("state-1")

    assert fake.calls == [("get", "/sources/connect/status", {"state": "state-1"})]


def test_disconnect(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(sources.http, "api", fake)

    sources.disconnect("source-1")

    assert fake.calls == [("post", "/sources/source-1/disconnect", None)]


def test_process_import(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(processing.http, "api", fake)

    processing.process_import("import-1")

    assert fake.calls == [("post", "/imports/import-1/process", None)]


def test_list_people(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(query.http, "api", fake)

    query.list_people()

    assert fake.calls == [("get", "/people", None)]


def test_search_people(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(query.http, "api", fake)

    query.search_people("Alex")

    assert fake.calls == [("get", "/people/search", {"q": "Alex"})]
