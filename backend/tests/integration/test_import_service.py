import uuid

import pytest
from sqlalchemy.orm import Session

from rosalind.ingestion import manifest, service
from rosalind.ingestion.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
)


def _entry(
    path: str = "a.json", sha256: str = "a" * 64, size: int = 1
) -> manifest.FileEntry:
    return manifest.FileEntry(path=path, sha256=sha256, size=size, format="json")


def test_create_and_complete_import(db_session: Session) -> None:
    imp = service.create_import(db_session, "google", "takeout")
    assert imp.status == "uploading"

    completed = service.complete_import(db_session, imp.id, [_entry()])
    assert completed.status == "completed"
    assert completed.file_count == 1
    assert completed.total_size == 1
    assert completed.import_hash is not None
    assert completed.completed_at is not None
    assert completed.files[0].storage_key == f"imports/{imp.id}/a.json"


def test_get_import_returns_files(db_session: Session) -> None:
    imp = service.create_import(db_session, "google", "takeout")
    service.complete_import(
        db_session, imp.id, [_entry("Contacts/contacts.json", "b" * 64, 42)]
    )

    fetched = service.get_import(db_session, imp.id)
    assert fetched.file_count == 1
    assert [f.path for f in fetched.files] == ["Contacts/contacts.json"]


def test_complete_import_twice_is_rejected(db_session: Session) -> None:
    imp = service.create_import(db_session, "google", "takeout")
    service.complete_import(db_session, imp.id, [_entry()])

    with pytest.raises(InvalidImportStateError):
        service.complete_import(db_session, imp.id, [_entry()])


def test_complete_import_unknown_id(db_session: Session) -> None:
    with pytest.raises(ImportNotFoundError):
        service.complete_import(db_session, uuid.uuid4(), [_entry()])


def test_complete_import_rejects_duplicate_paths(db_session: Session) -> None:
    imp = service.create_import(db_session, "google", "takeout")
    with pytest.raises(InvalidManifestError):
        service.complete_import(
            db_session, imp.id, [_entry("a.json"), _entry("a.json")]
        )


def test_complete_import_rejects_invalid_sha256(db_session: Session) -> None:
    imp = service.create_import(db_session, "google", "takeout")
    entry = manifest.FileEntry(path="a.json", sha256="bad", size=1)
    with pytest.raises(InvalidManifestError):
        service.complete_import(db_session, imp.id, [entry])


def test_get_import_unknown_id(db_session: Session) -> None:
    with pytest.raises(ImportNotFoundError):
        service.get_import(db_session, uuid.uuid4())


def test_list_imports_returns_all(db_session: Session) -> None:
    first = service.create_import(db_session, "google", "takeout")
    second = service.create_import(db_session, "apple", "takeout")

    imports = service.list_imports(db_session)

    assert {imp.id for imp in imports} == {first.id, second.id}


def test_list_imports_empty(db_session: Session) -> None:
    assert service.list_imports(db_session) == []


def test_delete_import(db_session: Session) -> None:
    imp = service.create_import(db_session, "google", "takeout")
    service.complete_import(db_session, imp.id, [_entry()])

    service.delete_import(db_session, imp.id)

    with pytest.raises(ImportNotFoundError):
        service.get_import(db_session, imp.id)


def test_delete_import_unknown_id(db_session: Session) -> None:
    with pytest.raises(ImportNotFoundError):
        service.delete_import(db_session, uuid.uuid4())
