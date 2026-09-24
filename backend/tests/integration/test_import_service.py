import uuid

import pytest

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application import manifest
from rosalind.application.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
)
from rosalind.application.services import imports
from rosalind.domain.source import SourceAccount


def _entry(
    path: str = "a.json", sha256: str = "a" * 64, size: int = 1
) -> manifest.FileEntry:
    return manifest.FileEntry(path=path, sha256=sha256, size=size, format="json")


def _source(uow: SqlAlchemyUnitOfWork) -> SourceAccount:
    return composition.source_service.create_source(
        uow, provider="google", name="google-personal"
    )


def test_create_and_complete_import(uow: SqlAlchemyUnitOfWork) -> None:
    source = _source(uow)
    imp = imports.create_import(uow, source, "takeout")
    assert imp.ingestion_status == "uploading"
    assert imp.processing_status == "pending"
    assert imp.source_account_id == source.id

    completed = imports.complete_import(uow, imp.id, [_entry()])
    assert completed.ingestion_status == "completed"
    assert completed.file_count == 1
    assert completed.total_size == 1
    assert completed.import_hash is not None
    assert completed.completed_at is not None
    assert completed.files[0].storage_key == f"imports/{imp.id}/a.json"


def test_get_import_returns_files(uow: SqlAlchemyUnitOfWork) -> None:
    source = _source(uow)
    imp = imports.create_import(uow, source, "takeout")
    imports.complete_import(
        uow, imp.id, [_entry("Contacts/contacts.json", "b" * 64, 42)]
    )

    fetched = imports.get_import(uow, imp.id)
    assert fetched.file_count == 1
    assert [f.path for f in fetched.files] == ["Contacts/contacts.json"]


def test_complete_import_twice_is_rejected(uow: SqlAlchemyUnitOfWork) -> None:
    source = _source(uow)
    imp = imports.create_import(uow, source, "takeout")
    imports.complete_import(uow, imp.id, [_entry()])

    with pytest.raises(InvalidImportStateError):
        imports.complete_import(uow, imp.id, [_entry()])


def test_complete_import_unknown_id(uow: SqlAlchemyUnitOfWork) -> None:
    with pytest.raises(ImportNotFoundError):
        imports.complete_import(uow, uuid.uuid4(), [_entry()])


def test_complete_import_rejects_duplicate_paths(uow: SqlAlchemyUnitOfWork) -> None:
    source = _source(uow)
    imp = imports.create_import(uow, source, "takeout")
    with pytest.raises(InvalidManifestError):
        imports.complete_import(uow, imp.id, [_entry("a.json"), _entry("a.json")])


def test_complete_import_rejects_invalid_sha256(uow: SqlAlchemyUnitOfWork) -> None:
    source = _source(uow)
    imp = imports.create_import(uow, source, "takeout")
    entry = manifest.FileEntry(path="a.json", sha256="bad", size=1)
    with pytest.raises(InvalidManifestError):
        imports.complete_import(uow, imp.id, [entry])


def test_get_import_unknown_id(uow: SqlAlchemyUnitOfWork) -> None:
    with pytest.raises(ImportNotFoundError):
        imports.get_import(uow, uuid.uuid4())


def test_list_imports_returns_all(uow: SqlAlchemyUnitOfWork) -> None:
    first_source = composition.source_service.create_source(
        uow, provider="google", name="google-personal"
    )
    second_source = composition.source_service.create_source(
        uow, provider="apple", name="apple-personal"
    )

    first = imports.create_import(uow, first_source, "takeout")
    second = imports.create_import(uow, second_source, "takeout")

    result = imports.list_imports(uow)

    assert {imp.id for imp in result} == {first.id, second.id}


def test_list_imports_empty(uow: SqlAlchemyUnitOfWork) -> None:
    assert imports.list_imports(uow) == []


def test_delete_import(uow: SqlAlchemyUnitOfWork) -> None:
    source = _source(uow)
    imp = imports.create_import(uow, source, "takeout")
    imports.complete_import(uow, imp.id, [_entry()])

    imports.delete_import(uow, imp.id)

    with pytest.raises(ImportNotFoundError):
        imports.get_import(uow, imp.id)


def test_delete_import_unknown_id(uow: SqlAlchemyUnitOfWork) -> None:
    with pytest.raises(ImportNotFoundError):
        imports.delete_import(uow, uuid.uuid4())


def test_create_import_requires_source(uow: SqlAlchemyUnitOfWork) -> None:
    from rosalind.application.errors import SourceNotFoundError

    with pytest.raises(SourceNotFoundError):
        composition.source_service.resolve_source(uow, "does-not-exist")
