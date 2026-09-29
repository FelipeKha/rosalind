from typer.testing import CliRunner

from cli import app
from cli.commands import process as process_module
from cli.commands import query as query_module

runner = CliRunner()


def test_process_run_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        process_module.client,
        "process_import",
        lambda import_id: {
            "import_id": import_id,
            "processing_status": "completed",
            "result": "ok",
            "people_created": 1,
            "facts_created": 2,
            "facts_reused": 0,
            "assertions_created": 3,
        },
    )
    result = runner.invoke(app, ["process", "run", "imp-1"])
    assert result.exit_code == 0
    assert "Processing import completed" in result.stdout


def test_process_run_unsupported(monkeypatch) -> None:
    monkeypatch.setattr(
        process_module.client,
        "process_import",
        lambda import_id: {
            "import_id": import_id,
            "processing_status": "pending",
            "result": "unsupported",
            "message": "No parser available for this import type.",
        },
    )
    result = runner.invoke(app, ["process", "run", "imp-1"])
    assert result.exit_code == 0
    assert "No parser available" in result.stdout


def test_process_run_error(monkeypatch) -> None:
    def raise_error(import_id: str) -> dict[str, object]:
        raise process_module.ApiClientError("boom")

    monkeypatch.setattr(process_module.client, "process_import", raise_error)
    result = runner.invoke(app, ["process", "run", "imp-1"])
    assert result.exit_code == 1
    assert "Failed to process import" in result.stderr


def test_query_people(monkeypatch) -> None:
    monkeypatch.setattr(
        query_module.client,
        "list_people",
        lambda: [
            {
                "person_id": "p-1",
                "display_name": "Alex Morgan",
                "primary_email": "alex@example.com",
            }
        ],
    )
    result = runner.invoke(app, ["query", "people"])
    assert result.exit_code == 0
    assert "Alex Morgan" in result.stdout


def test_query_people_search(monkeypatch) -> None:
    calls: list[str] = []

    def fake_search(q: str) -> list[dict[str, object]]:
        calls.append(q)
        return []

    monkeypatch.setattr(query_module.client, "search_people", fake_search)
    result = runner.invoke(app, ["query", "people", "--search", "Alex"])
    assert result.exit_code == 0
    assert calls == ["Alex"]


def test_query_people_error(monkeypatch) -> None:
    def raise_error() -> list[dict[str, object]]:
        raise query_module.ApiClientError("boom")

    monkeypatch.setattr(query_module.client, "list_people", raise_error)
    result = runner.invoke(app, ["query", "people"])
    assert result.exit_code == 1
    assert "Failed to query people" in result.stderr


def test_query_person(monkeypatch) -> None:
    monkeypatch.setattr(
        query_module.client,
        "get_person",
        lambda person_id: {
            "person_id": person_id,
            "display_name": "Alex Morgan",
            "primary_email": "alex@example.com",
            "gender": None,
            "locale": None,
            "birth_year": None,
            "birth_month": None,
            "birth_day": None,
        },
    )
    result = runner.invoke(app, ["query", "person", "p-1"])
    assert result.exit_code == 0
    assert "Alex Morgan" in result.stdout


def test_query_person_error(monkeypatch) -> None:
    def raise_error(person_id: str) -> dict[str, object]:
        raise query_module.ApiClientError("boom")

    monkeypatch.setattr(query_module.client, "get_person", raise_error)
    result = runner.invoke(app, ["query", "person", "p-1"])
    assert result.exit_code == 1
    assert "Failed to get person" in result.stderr
