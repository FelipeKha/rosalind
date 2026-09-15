from pathlib import Path

from typer.testing import CliRunner

from cli import app
from cli.commands import import_commands

runner = CliRunner()


class _FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str]] = []

    def upload_file(self, local_path: Path, bucket: str, object_key: str) -> None:
        self.uploads.append((str(local_path), bucket, object_key))


def _stub_backend(monkeypatch) -> None:
    monkeypatch.setattr(
        import_commands.client,
        "create_import",
        lambda source, type_: {
            "import_id": "imp-1",
            "storage_prefix": "imports/imp-1",
            "bucket": "rosalind",
        },
    )
    monkeypatch.setattr(
        import_commands.client,
        "complete_import",
        lambda import_id, manifest: {
            "import_id": "imp-1",
            "source": "google",
            "type": "takeout",
            "status": "completed",
            "file_count": 1,
            "total_size": 2,
            "import_hash": "abc123",
        },
    )


def test_import_create_google_success(monkeypatch, tmp_path) -> None:
    (tmp_path / "Contacts").mkdir()
    (tmp_path / "Contacts" / "contacts.json").write_text("{}")

    _stub_backend(monkeypatch)
    fake = _FakeStorage()
    monkeypatch.setattr(import_commands, "S3ObjectStorage", lambda: fake)

    result = runner.invoke(app, ["import", "create", "google", str(tmp_path)])

    assert result.exit_code == 0
    assert "Import completed" in result.stdout
    assert fake.uploads == [
        (
            str(tmp_path / "Contacts" / "contacts.json"),
            "rosalind",
            "imports/imp-1/Contacts/contacts.json",
        )
    ]


def test_import_create_google_missing_path(monkeypatch) -> None:
    result = runner.invoke(app, ["import", "create", "google", "/does/not/exist"])
    assert result.exit_code == 1
    assert "does not exist" in result.stderr


def test_import_create_google_path_is_not_directory(monkeypatch, tmp_path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("x")
    result = runner.invoke(app, ["import", "create", "google", str(file_path)])
    assert result.exit_code == 1
    assert "not a directory" in result.stderr


def test_import_create_google_create_import_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        import_commands.client,
        "create_import",
        lambda source, type_: (_ for _ in ()).throw(
            import_commands.client.ApiClientError("boom")
        ),
    )
    result = runner.invoke(app, ["import", "create", "google", str(tmp_path)])
    assert result.exit_code == 1
    assert "Failed to create import" in result.stderr
