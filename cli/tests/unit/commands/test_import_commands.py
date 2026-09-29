from pathlib import Path

from typer.testing import CliRunner

from cli import app
from cli.commands import import_

runner = CliRunner()


class _FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str]] = []

    def upload_file(self, local_path: Path, bucket: str, object_key: str) -> None:
        self.uploads.append((str(local_path), bucket, object_key))


def _stub_backend(monkeypatch) -> None:
    monkeypatch.setattr(
        import_.client,
        "create_import",
        lambda source, type_: {
            "import_id": "imp-1",
            "storage_prefix": "imports/imp-1",
            "bucket": "rosalind",
        },
    )
    monkeypatch.setattr(
        import_.client,
        "complete_import",
        lambda import_id, manifest: {
            "import_id": "imp-1",
            "source_name": "google-personal",
            "type": "takeout",
            "ingestion_status": "completed",
            "processing_status": "pending",
            "file_count": 1,
            "total_size": 2,
            "import_hash": "abc123",
        },
    )


def test_import_create_takeout_success(monkeypatch, tmp_path) -> None:
    (tmp_path / "Contacts").mkdir()
    (tmp_path / "Contacts" / "contacts.json").write_text("{}")

    _stub_backend(monkeypatch)
    fake = _FakeStorage()
    monkeypatch.setattr(import_, "S3ObjectStorage", lambda: fake)

    result = runner.invoke(
        app,
        [
            "import",
            "create",
            "--source",
            "google-personal",
            "--type",
            "takeout",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "Import completed" in result.stdout
    assert fake.uploads == [
        (
            str(tmp_path / "Contacts" / "contacts.json"),
            "rosalind",
            "imports/imp-1/Contacts/contacts.json",
        )
    ]


def test_import_create_takeout_missing_path(monkeypatch) -> None:
    result = runner.invoke(
        app,
        [
            "import",
            "create",
            "--source",
            "google-personal",
            "--type",
            "takeout",
            "/does/not/exist",
        ],
    )
    assert result.exit_code == 1
    assert "does not exist" in result.stderr


def test_import_create_takeout_requires_path(monkeypatch) -> None:
    result = runner.invoke(
        app, ["import", "create", "--source", "google-personal", "--type", "takeout"]
    )
    assert result.exit_code == 2
    assert "path is required" in result.stderr.lower()


def test_import_create_api_success(monkeypatch) -> None:
    monkeypatch.setattr(
        import_.client,
        "create_import",
        lambda source, type_: {
            "import_id": "imp-1",
            "source_name": source,
            "type": "api",
            "ingestion_status": "completed",
            "processing_status": "completed",
        },
    )

    result = runner.invoke(
        app,
        ["import", "create", "--source", "google-personal", "--type", "api"],
    )

    assert result.exit_code == 0
    assert "Import completed" in result.stdout


def test_import_create_unknown_type(monkeypatch) -> None:
    result = runner.invoke(
        app, ["import", "create", "--source", "s", "--type", "bogus"]
    )
    assert result.exit_code == 2


def test_import_create_create_import_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        import_.client,
        "create_import",
        lambda source, type_: (_ for _ in ()).throw(import_.ApiClientError("boom")),
    )
    result = runner.invoke(
        app,
        [
            "import",
            "create",
            "--source",
            "google-personal",
            "--type",
            "takeout",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "Failed to create import" in result.stderr
