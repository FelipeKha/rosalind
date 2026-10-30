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
        lambda source, via: {
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
            "source_name": "none",
            "via": "file",
            "ingestion_status": "completed",
            "processing_status": "pending",
            "file_count": 1,
            "total_size": 2,
            "import_hash": "abc123",
        },
    )


def test_import_create_folder_success(monkeypatch, tmp_path) -> None:
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
            "google",
            "--via",
            "file",
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


def test_import_create_single_file_success(monkeypatch, tmp_path) -> None:
    mbox = tmp_path / "rosalind_synthetic_emails.mbox"
    mbox.write_bytes(b"From a@b\n\nbody\n")

    _stub_backend(monkeypatch)
    fake = _FakeStorage()
    monkeypatch.setattr(import_, "S3ObjectStorage", lambda: fake)

    result = runner.invoke(app, ["import", "create", str(mbox)])

    assert result.exit_code == 0
    assert fake.uploads == [
        (str(mbox), "rosalind", "imports/imp-1/rosalind_synthetic_emails.mbox")
    ]


def test_import_create_defaults_source_to_none(monkeypatch, tmp_path) -> None:
    path = tmp_path / "mail.mbox"
    path.write_text("x")
    captured: dict[str, str] = {}

    def fake_create(source: str, via: str) -> dict[str, str]:
        captured["source"] = source
        captured["via"] = via
        return {
            "import_id": "imp-1",
            "storage_prefix": "imports/imp-1",
            "bucket": "rosalind",
        }

    monkeypatch.setattr(import_.client, "create_import", fake_create)
    monkeypatch.setattr(
        import_.client,
        "complete_import",
        lambda import_id, manifest: {
            "import_id": "imp-1",
            "source_name": "none",
            "via": "file",
            "ingestion_status": "completed",
            "processing_status": "pending",
            "file_count": 1,
            "total_size": 1,
            "import_hash": "abc123",
        },
    )
    monkeypatch.setattr(import_, "S3ObjectStorage", _FakeStorage)

    result = runner.invoke(app, ["import", "create", str(path)])

    assert result.exit_code == 0
    assert captured == {"source": "none", "via": "file"}


def test_import_create_missing_path(monkeypatch) -> None:
    result = runner.invoke(app, ["import", "create", "/does/not/exist"])
    assert result.exit_code == 1
    assert "does not exist" in result.stderr


def test_import_create_requires_path(monkeypatch) -> None:
    result = runner.invoke(app, ["import", "create", "--via", "file"])
    assert result.exit_code == 2
    assert "path is required" in result.stderr.lower()


def test_import_create_api_success(monkeypatch) -> None:
    monkeypatch.setattr(
        import_.client,
        "create_import",
        lambda source, via: {
            "import_id": "imp-1",
            "source_name": source,
            "via": via,
            "ingestion_status": "completed",
            "processing_status": "completed",
        },
    )

    result = runner.invoke(
        app, ["import", "create", "--source", "google", "--via", "api"]
    )

    assert result.exit_code == 0
    assert "Import completed" in result.stdout


def test_import_create_api_requires_google(monkeypatch) -> None:
    result = runner.invoke(app, ["import", "create", "--via", "api"])
    assert result.exit_code == 2
    assert "requires --source google" in result.stderr


def test_import_create_api_rejects_path(monkeypatch, tmp_path) -> None:
    result = runner.invoke(
        app,
        ["import", "create", "--source", "google", "--via", "api", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "does not take a path" in result.stderr


def test_import_create_rejects_unknown_source(monkeypatch, tmp_path) -> None:
    result = runner.invoke(
        app, ["import", "create", "--source", "dropbox", str(tmp_path)]
    )
    assert result.exit_code == 2


def test_import_create_create_import_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        import_.client,
        "create_import",
        lambda source, via: (_ for _ in ()).throw(import_.ApiClientError("boom")),
    )
    result = runner.invoke(app, ["import", "create", str(tmp_path)])
    assert result.exit_code == 1
    assert "Failed to create import" in result.stderr
