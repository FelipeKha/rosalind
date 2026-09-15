from typer.testing import CliRunner

from cli import app
from cli.commands import import_commands

runner = CliRunner()


def test_show_import(monkeypatch) -> None:
    monkeypatch.setattr(
        import_commands.client,
        "get_import",
        lambda import_id: {
            "import_id": import_id,
            "source": "google",
            "type": "takeout",
            "status": "completed",
            "file_count": 1,
            "total_size": 10,
            "import_hash": "abc123",
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
        raise import_commands.client.ApiClientError("boom")

    monkeypatch.setattr(import_commands.client, "get_import", raise_error)
    result = runner.invoke(app, ["import", "show", "imp-1"])
    assert result.exit_code == 1
    assert "Failed to get import" in result.stderr
