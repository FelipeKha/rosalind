from typer.testing import CliRunner

from cli import app
from cli.commands import search as search_module

runner = CliRunner()

_RESULT = {
    "request_id": "req-1",
    "audit_id": "aud-1",
    "mode_requested": "hybrid",
    "mode_effective": "hybrid",
    "applied_filters": {},
    "warnings": [],
    "results": [
        {
            "item_id": "item-1",
            "thread_id": None,
            "chunk_id": "chunk-1",
            "subject": "Slate invoice",
            "sender": "roofer@example.com",
            "date": "2024-03-04T10:00:00Z",
            "snippet": "$8,400 for the slate replacement",
            "matched_in": "body",
            "score": 0.9123,
            "citation": {
                "item_id": "item-1",
                "chunk_id": "chunk-1",
                "thread_id": None,
            },
        }
    ],
    "total_estimate": 1,
    "next_cursor": None,
}


def test_search_renders_results(monkeypatch) -> None:
    monkeypatch.setattr(search_module.client, "search", lambda *a, **k: _RESULT)

    result = runner.invoke(app, ["search", "roofer"])

    assert result.exit_code == 0
    assert "roofer@example.com" in result.stdout
    assert "Slate invoice" in result.stdout
    assert "0.912" in result.stdout
    assert "$8,400 for the slate replacement" in result.stdout


def test_search_json(monkeypatch) -> None:
    monkeypatch.setattr(search_module.client, "search", lambda *a, **k: _RESULT)

    result = runner.invoke(app, ["--json", "search", "roofer"])

    assert result.exit_code == 0
    assert '"item_id": "item-1"' in result.stdout


def test_search_empty(monkeypatch) -> None:
    empty = dict(_RESULT, results=[], total_estimate=0)
    monkeypatch.setattr(search_module.client, "search", lambda *a, **k: empty)

    result = runner.invoke(app, ["search", "nope"])

    assert result.exit_code == 0
    assert "No results found." in result.stdout


def test_search_short_circuit(monkeypatch) -> None:
    monkeypatch.setattr(
        search_module.client,
        "search",
        lambda *a, **k: {
            "request_id": "req-1",
            "audit_id": "aud-1",
            "short_circuit": "empty_query",
            "explanation": "Add a query or at least one filter.",
            "results": [],
        },
    )

    result = runner.invoke(app, ["search"])

    assert result.exit_code == 0
    assert "Add a query or at least one filter." in result.stdout
    assert "No results found." not in result.stdout


def test_search_error(monkeypatch) -> None:
    def raise_error(*a, **k):
        raise search_module.ApiClientError("boom")

    monkeypatch.setattr(search_module.client, "search", raise_error)

    result = runner.invoke(app, ["search", "roofer"])

    assert result.exit_code == 1
    assert "Failed to search" in result.stderr


def test_search_invalid_date(monkeypatch) -> None:
    monkeypatch.setattr(search_module.client, "search", lambda *a, **k: _RESULT)

    result = runner.invoke(app, ["search", "--since", "not-a-date"])

    assert result.exit_code == 2
    assert "invalid date" in result.stderr


def test_search_limit_out_of_range(monkeypatch) -> None:
    monkeypatch.setattr(search_module.client, "search", lambda *a, **k: _RESULT)

    result = runner.invoke(app, ["search", "roofer", "--limit", "99"])

    assert result.exit_code == 2
    assert "--limit must be between" in result.stderr


def test_search_forwards_repeated_sender(monkeypatch) -> None:
    captured: dict = {}

    def fake(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return _RESULT

    monkeypatch.setattr(search_module.client, "search", fake)

    result = runner.invoke(
        app, ["search", "q", "--sender", "a@example.com", "--sender", "b@example.com"]
    )

    assert result.exit_code == 0
    assert captured["sender"] == ["a@example.com", "b@example.com"]
    assert captured["mode"] == "hybrid"
    assert captured["limit"] == 10
