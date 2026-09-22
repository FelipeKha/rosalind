import uuid

import pytest
from sqlalchemy.orm import Session

from rosalind.adapters.inbound.ingestion import manifest
from rosalind.adapters.inbound.ingestion.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
)
from rosalind.adapters.outbound.persistence import models
from rosalind.services import imports, sources


def _entry(
    path: str = "a.json", sha256: str = "a" * 64, size: int = 1
) -> manifest.FileEntry:
    return manifest.FileEntry(path=path, sha256=sha256, size=size, format="json")


def _source(db: Session) -> models.SourceAccount:
    return sources.create_source(db, provider="google", name="google-personal")


def test_create_and_complete_import(db_session: Session) -> None:
    source = _source(db_session)
    imp = imports.create_import(db_session, source, "takeout")
    assert imp.ingestion_status == "uploading"
    assert imp.processing_status == "pending"
    assert imp.source_account_id == source.id

    completed = imports.complete_import(db_session, imp.id, [_entry()])
    assert completed.ingestion_status == "completed"
    assert completed.file_count == 1
    assert completed.total_size == 1
    assert completed.import_hash is not None
    assert completed.completed_at is not None
    assert completed.files[0].storage_key == f"imports/{imp.id}/a.json"


def test_get_import_returns_files(db_session: Session) -> None:
    source = _source(db_session)
    imp = imports.create_import(db_session, source, "takeout")
    imports.complete_import(
        db_session, imp.id, [_entry("Contacts/contacts.json", "b" * 64, 42)]
    )

    fetched = imports.get_import(db_session, imp.id)
    assert fetched.file_count == 1
    assert [f.path for f in fetched.files] == ["Contacts/contacts.json"]


def test_complete_import_twice_is_rejected(db_session: Session) -> None:
    source = _source(db_session)
    imp = imports.create_import(db_session, source, "takeout")
    imports.complete_import(db_session, imp.id, [_entry()])

    with pytest.raises(InvalidImportStateError):
        imports.complete_import(db_session, imp.id, [_entry()])


def test_complete_import_unknown_id(db_session: Session) -> None:
    with pytest.raises(ImportNotFoundError):
        imports.complete_import(db_session, uuid.uuid4(), [_entry()])


def test_complete_import_rejects_duplicate_paths(db_session: Session) -> None:
    source = _source(db_session)
    imp = imports.create_import(db_session, source, "takeout")
    with pytest.raises(InvalidManifestError):
        imports.complete_import(
            db_session, imp.id, [_entry("a.json"), _entry("a.json")]
        )


def test_complete_import_rejects_invalid_sha256(db_session: Session) -> None:
    source = _source(db_session)
    imp = imports.create_import(db_session, source, "takeout")
    entry = manifest.FileEntry(path="a.json", sha256="bad", size=1)
    with pytest.raises(InvalidManifestError):
        imports.complete_import(db_session, imp.id, [entry])


def test_get_import_unknown_id(db_session: Session) -> None:
    with pytest.raises(ImportNotFoundError):
        imports.get_import(db_session, uuid.uuid4())


def test_list_imports_returns_all(db_session: Session) -> None:
    first_source = sources.create_source(
        db_session, provider="google", name="google-personal"
    )
    second_source = sources.create_source(
        db_session, provider="apple", name="apple-personal"
    )

    first = imports.create_import(db_session, first_source, "takeout")
    second = imports.create_import(db_session, second_source, "takeout")

    result = imports.list_imports(db_session)

    assert {imp.id for imp in result} == {first.id, second.id}


def test_list_imports_empty(db_session: Session) -> None:
    assert imports.list_imports(db_session) == []


def test_delete_import(db_session: Session) -> None:
    source = _source(db_session)
    imp = imports.create_import(db_session, source, "takeout")
    imports.complete_import(db_session, imp.id, [_entry()])

    imports.delete_import(db_session, imp.id)

    with pytest.raises(ImportNotFoundError):
        imports.get_import(db_session, imp.id)


def test_delete_import_unknown_id(db_session: Session) -> None:
    with pytest.raises(ImportNotFoundError):
        imports.delete_import(db_session, uuid.uuid4())


def test_create_import_requires_source(db_session: Session) -> None:
    from rosalind.adapters.outbound.google.errors import SourceNotFoundError

    with pytest.raises(SourceNotFoundError):
        sources.resolve_source(db_session, "does-not-exist")
