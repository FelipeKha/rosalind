from typer.testing import CliRunner

from cli import app
from cli.commands import import_commands

runner = CliRunner()


def _summary(import_id: str = "imp-1") -> dict[str, object]:
    return {
        "import_id": import_id,
        "source": "google",
        "type": "takeout",
        "status": "completed",
        "created_at": "2026-09-15T00:00:00Z",
        "completed_at": "2026-09-15T00:00:01Z",
        "file_count": 2,
        "total_size": 4096,
        "import_hash": "abc123",
    }


def test_list_imports_empty(monkeypatch) -> None:
    monkeypatch.setattr(import_commands.client, "list_imports", list)
    result = runner.invoke(app, ["import", "list"])
    assert result.exit_code == 0
    assert "No imports found" in result.stdout


def test_list_imports(monkeypatch) -> None:
    monkeypatch.setattr(import_commands.client, "list_imports", lambda: [_summary()])
    result = runner.invoke(app, ["import", "list"])
    assert result.exit_code == 0
    assert "imp-1" in result.stdout
    assert "ID" in result.stdout and "SOURCE" in result.stdout
    assert "2026-09-" in result.stdout


def test_list_imports_error(monkeypatch) -> None:
    def raise_error() -> list[dict[str, object]]:
        raise import_commands.client.ApiClientError("boom")

    monkeypatch.setattr(import_commands.client, "list_imports", raise_error)
    result = runner.invoke(app, ["import", "list"])
    assert result.exit_code == 1
    assert "Failed to list imports" in result.stderr


def test_delete_import_confirmed(monkeypatch) -> None:
    deleted: list[str] = []

    monkeypatch.setattr(
        import_commands.client,
        "delete_import",
        lambda import_id: deleted.append(import_id),
    )
    result = runner.invoke(app, ["import", "delete", "imp-1", "--yes"])
    assert result.exit_code == 0
    assert deleted == ["imp-1"]
    assert "deleted" in result.stdout


def test_delete_import_aborts_when_declined(monkeypatch) -> None:
    called = []

    monkeypatch.setattr(
        import_commands.client,
        "delete_import",
        lambda import_id: called.append(import_id),
    )
    result = runner.invoke(app, ["import", "delete", "imp-1"], input="n\n")
    assert result.exit_code == 1
    assert called == []


def test_delete_import_error(monkeypatch) -> None:
    def raise_error(import_id: str) -> None:
        raise import_commands.client.ApiClientError("boom")

    monkeypatch.setattr(import_commands.client, "delete_import", raise_error)
    result = runner.invoke(app, ["import", "delete", "imp-1", "--yes"])
    assert result.exit_code == 1
    assert "Failed to delete import" in result.stderr
