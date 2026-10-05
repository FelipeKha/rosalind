from __future__ import annotations

from rosalind.adapters.outbound.google import auth as google_auth
from rosalind.adapters.outbound.google import people as google_people


class _FakeRequest:
    def __init__(self, parent: _FakeConnections, idx: int = 0) -> None:
        self._parent = parent
        self._idx = idx

    def execute(self) -> dict:
        return self._parent.pages[self._idx]


class _FakeConnections:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.list_kwargs: dict | None = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return _FakeRequest(self, 0)

    def list_next(self, request: _FakeRequest, response: dict):
        next_idx = request._idx + 1
        if next_idx < len(self.pages):
            return _FakeRequest(self, next_idx)
        return None


class _FakeService:
    def __init__(self, connections: _FakeConnections) -> None:
        self._connections = connections

    def people(self):
        return self

    def connections(self) -> _FakeConnections:
        return self._connections


def _patch(monkeypatch, connections: _FakeConnections) -> _FakeConnections:
    monkeypatch.setattr(
        google_auth, "build_people_service", lambda creds: _FakeService(connections)
    )
    return connections


def test_fetch_contacts_paginates_and_captures_sync_token(monkeypatch) -> None:
    connections = _patch(
        monkeypatch,
        _FakeConnections(
            [
                {
                    "connections": [
                        {"resourceName": "people/1"},
                        {"resourceName": "people/2"},
                    ]
                },
                {
                    "connections": [{"resourceName": "people/3"}],
                    "nextSyncToken": "sync-token-1",
                },
            ]
        ),
    )

    fetch = google_people.fetch_contacts(object())  # type: ignore[arg-type]

    assert [c["resourceName"] for c in fetch.contacts] == [
        "people/1",
        "people/2",
        "people/3",
    ]
    assert fetch.next_sync_token == "sync-token-1"
    assert fetch.sync_parameters is not None
    assert fetch.sync_parameters["sort_order"] == "LAST_MODIFIED_ASCENDING"
    assert "names" in fetch.sync_parameters["person_fields"]
    assert connections.list_kwargs is not None
    assert connections.list_kwargs["requestSyncToken"] is True
    assert connections.list_kwargs["pageSize"] == 1000


def test_fetch_contacts_no_sync_token_on_single_page(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _FakeConnections([{"connections": [{"resourceName": "people/1"}]}]),
    )

    fetch = google_people.fetch_contacts(object())  # type: ignore[arg-type]

    assert len(fetch.contacts) == 1
    assert fetch.next_sync_token is None


def test_fetch_contacts_empty_contacts(monkeypatch) -> None:
    _patch(monkeypatch, _FakeConnections([{"connections": []}]))

    fetch = google_people.fetch_contacts(object())  # type: ignore[arg-type]

    assert fetch.contacts == ()
    assert fetch.next_sync_token is None
