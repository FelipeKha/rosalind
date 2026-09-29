from typer.testing import CliRunner

from cli import app
from cli.commands import import_

runner = CliRunner()


def _summary(import_id: str = "imp-1") -> dict[str, object]:
    return {
        "import_id": import_id,
        "source_name": "google-personal",
        "type": "takeout",
        "ingestion_status": "completed",
        "processing_status": "pending",
        "file_count": 2,
        "total_size": 4096,
        "import_hash": "abc123",
    }


def test_list_imports_empty(monkeypatch) -> None:
    monkeypatch.setattr(import_.client, "list_imports", list)
    result = runner.invoke(app, ["import", "list"])
    assert result.exit_code == 0
    assert "No imports found" in result.stdout


def test_list_imports(monkeypatch) -> None:
    monkeypatch.setattr(import_.client, "list_imports", lambda: [_summary()])
    result = runner.invoke(app, ["import", "list"])
    assert result.exit_code == 0
    assert "imp-1" in result.stdout
    assert "INGESTION" in result.stdout and "PROCESSING" in result.stdout


def test_list_imports_json(monkeypatch) -> None:
    monkeypatch.setattr(import_.client, "list_imports", lambda: [_summary()])
    result = runner.invoke(app, ["--json", "import", "list"])
    assert result.exit_code == 0
    assert '"import_id"' in result.stdout


def test_list_imports_error(monkeypatch) -> None:
    def raise_error() -> list[dict[str, object]]:
        raise import_.ApiClientError("boom")

    monkeypatch.setattr(import_.client, "list_imports", raise_error)
    result = runner.invoke(app, ["import", "list"])
    assert result.exit_code == 1
    assert "Failed to list imports" in result.stderr


def test_delete_import_confirmed(monkeypatch) -> None:
    deleted: list[str] = []

    monkeypatch.setattr(
        import_.client,
        "delete_import",
        lambda import_id: deleted.append(import_id),
    )
    result = runner.invoke(app, ["import", "delete", "imp-1", "--yes"])
    assert result.exit_code == 0
    assert deleted == ["imp-1"]
    assert "deleted" in result.stdout


def test_delete_import_aborts_when_declined(monkeypatch) -> None:
    called: list[str] = []

    monkeypatch.setattr(
        import_.client,
        "delete_import",
        lambda import_id: called.append(import_id),
    )
    result = runner.invoke(app, ["import", "delete", "imp-1"], input="n\n")
    assert result.exit_code == 1
    assert called == []


def test_delete_import_error(monkeypatch) -> None:
    def raise_error(import_id: str) -> None:
        raise import_.ApiClientError("boom")

    monkeypatch.setattr(import_.client, "delete_import", raise_error)
    result = runner.invoke(app, ["import", "delete", "imp-1", "--yes"])
    assert result.exit_code == 1
    assert "Failed to delete import" in result.stderr


def test_show_import(monkeypatch) -> None:
    monkeypatch.setattr(
        import_.client,
        "get_import",
        lambda import_id: {
            **_summary(import_id),
            "files": [
                {
                    "path": "Contacts/contacts.json",
                    "sha256": "a" * 64,
                    "size": 10,
                    "format": "json",
                    "modified_at": None,
                    "storage_key": f"imports/{import_id}/Contacts/contacts.json",
                }
            ],
        },
    )
    result = runner.invoke(app, ["import", "show", "imp-1"])
    assert result.exit_code == 0
    assert "imp-1" in result.stdout
    assert "Contacts/contacts.json" in result.stdout


def test_show_import_error(monkeypatch) -> None:
    def raise_error(import_id: str) -> dict[str, object]:
        raise import_.ApiClientError("boom")

    monkeypatch.setattr(import_.client, "get_import", raise_error)
    result = runner.invoke(app, ["import", "show", "imp-1"])
    assert result.exit_code == 1
    assert "Failed to get import" in result.stderr
