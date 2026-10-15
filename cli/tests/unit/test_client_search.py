from datetime import date

from cli import config
from cli.client import search as client


class FakeApi:
    def __init__(self):
        self.calls = []
        self.timeouts = []

    def post(self, path, *, json=None, timeout=None):
        self.calls.append(("post", path, json))
        self.timeouts.append(timeout)
        return {}


def test_search_minimal(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(client.http, "api", fake)

    client.search()

    assert fake.calls == [("post", "/search", {"mode": "hybrid", "limit": 10})]


def test_search_full(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(client.http, "api", fake)

    client.search(
        "roofer invoice",
        keywords="slate",
        sender=["a@example.com", "b@example.com"],
        since=date(2024, 1, 1),
        before=date(2024, 2, 1),
        has_attachment=True,
        mode="semantic",
        limit=25,
        cursor="cur-1",
    )

    assert fake.calls == [
        (
            "post",
            "/search",
            {
                "mode": "semantic",
                "limit": 25,
                "query": "roofer invoice",
                "keywords": "slate",
                "cursor": "cur-1",
                "filters": {
                    "sender": ["a@example.com", "b@example.com"],
                    "date_from": "2024-01-01",
                    "date_before": "2024-02-01",
                    "has_attachment": True,
                },
            },
        )
    ]


def test_search_uses_configured_timeout(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(client.http, "api", fake)
    monkeypatch.setenv("ROSALIND_SEARCH_TIMEOUT", "30")

    client.search("hello")

    assert fake.timeouts == [30.0]
    assert config.search_timeout() == 30.0


def test_search_omits_empty_filters(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(client.http, "api", fake)

    client.search("hello", has_attachment=False)

    assert fake.calls == [
        (
            "post",
            "/search",
            {
                "mode": "hybrid",
                "limit": 10,
                "query": "hello",
                "filters": {"has_attachment": False},
            },
        )
    ]
