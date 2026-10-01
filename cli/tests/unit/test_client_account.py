"""Unit tests for the account client (``/me``)."""

from __future__ import annotations

from cli.client import account


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get(self, path: str, *, params=None):
        self.calls.append(("get", path, params))
        return {"account_id": "abc", "email": "jane@example.com"}


def test_whoami(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setattr(account.http, "api", fake)

    result = account.whoami()

    assert fake.calls == [("get", "/me", None)]
    assert result["email"] == "jane@example.com"
