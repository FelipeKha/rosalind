import uuid
from collections.abc import Callable, Sequence

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
from tests._account import ensure_account

SOURCE_NAME = "google-personal"


class _FakeStorage:
    bucket: str
    deleted: list[str]

    def __init__(self) -> None:
        self.bucket = "test-bucket"
        self.deleted = []
        self.on_delete: Callable[[Sequence[str]], None] | None = None

    def delete_objects(self, keys: Sequence[str]) -> None:
        self.deleted.extend(keys)
        if self.on_delete is not None:
            self.on_delete(keys)


def _service(storage: _FakeStorage | None = None) -> imports.ImportService:
    return imports.ImportService(
        storage=storage or _FakeStorage(),
        sources=composition.source_service,
        processing=composition.processing_service,
    )


def _entry(
    path: str = "a.json", sha256: str = "a" * 64, size: int = 1
) -> manifest.FileEntry:
    return manifest.FileEntry(path=path, sha256=sha256, size=size, format="json")


def _account_id(uow: SqlAlchemyUnitOfWork) -> uuid.UUID:
    return ensure_account(uow).id


def _source(uow: SqlAlchemyUnitOfWork) -> SourceAccount:
    return composition.source_service.create_source(
        uow, _account_id(uow), provider="google", name=SOURCE_NAME
    )


def test_create_and_complete_import(uow: SqlAlchemyUnitOfWork) -> None:
    source = _source(uow)
    account_id = _account_id(uow)
    svc = _service()
    imp = svc.create_import(uow, account_id, SOURCE_NAME, "takeout")
    assert imp.ingestion_status == "uploading"
    assert imp.processing_status == "pending"
    assert imp.source_account_id == source.id

    completed = svc.complete_import(uow, account_id, imp.id, [_entry()])
    assert completed.ingestion_status == "completed"
    assert completed.file_count == 1
    assert completed.total_size == 1
    assert completed.import_hash is not None
    assert completed.completed_at is not None
    assert completed.files[0].storage_key == f"imports/{imp.id}/a.json"


def test_get_import_returns_files(uow: SqlAlchemyUnitOfWork) -> None:
    _source(uow)
    account_id = _account_id(uow)
    svc = _service()
    imp = svc.create_import(uow, account_id, SOURCE_NAME, "takeout")
    svc.complete_import(
        uow, account_id, imp.id, [_entry("Contacts/contacts.json", "b" * 64, 42)]
    )

    fetched = svc.get_import(uow, account_id, imp.id)
    assert fetched.file_count == 1
    assert [f.path for f in fetched.files] == ["Contacts/contacts.json"]


def test_complete_import_twice_is_rejected(uow: SqlAlchemyUnitOfWork) -> None:
    _source(uow)
    account_id = _account_id(uow)
    svc = _service()
    imp = svc.create_import(uow, account_id, SOURCE_NAME, "takeout")
    svc.complete_import(uow, account_id, imp.id, [_entry()])

    with pytest.raises(InvalidImportStateError):
        svc.complete_import(uow, account_id, imp.id, [_entry()])


def test_complete_import_unknown_id(uow: SqlAlchemyUnitOfWork) -> None:
    svc = _service()
    account_id = _account_id(uow)
    with pytest.raises(ImportNotFoundError):
        svc.complete_import(uow, account_id, uuid.uuid4(), [_entry()])


def test_complete_import_rejects_duplicate_paths(uow: SqlAlchemyUnitOfWork) -> None:
    _source(uow)
    account_id = _account_id(uow)
    svc = _service()
    imp = svc.create_import(uow, account_id, SOURCE_NAME, "takeout")
    with pytest.raises(InvalidManifestError):
        svc.complete_import(
            uow, account_id, imp.id, [_entry("a.json"), _entry("a.json")]
        )


def test_complete_import_rejects_invalid_sha256(uow: SqlAlchemyUnitOfWork) -> None:
    _source(uow)
    account_id = _account_id(uow)
    svc = _service()
    imp = svc.create_import(uow, account_id, SOURCE_NAME, "takeout")
    entry = manifest.FileEntry(path="a.json", sha256="bad", size=1)
    with pytest.raises(InvalidManifestError):
        svc.complete_import(uow, account_id, imp.id, [entry])


def test_get_import_unknown_id(uow: SqlAlchemyUnitOfWork) -> None:
    svc = _service()
    account_id = _account_id(uow)
    with pytest.raises(ImportNotFoundError):
        svc.get_import(uow, account_id, uuid.uuid4())


def test_list_imports_returns_all(uow: SqlAlchemyUnitOfWork) -> None:
    account_id = _account_id(uow)
    composition.source_service.create_source(
        uow, account_id, provider="google", name="google-personal"
    )
    composition.source_service.create_source(
        uow, account_id, provider="apple", name="apple-personal"
    )
    svc = _service()

    first = svc.create_import(uow, account_id, "google-personal", "takeout")
    second = svc.create_import(uow, account_id, "apple-personal", "takeout")

    result = svc.list_imports(uow, account_id)

    assert {imp.id for imp in result} == {first.id, second.id}


def test_list_imports_empty(uow: SqlAlchemyUnitOfWork) -> None:
    account_id = _account_id(uow)
    assert _service().list_imports(uow, account_id) == []


def test_delete_import(uow: SqlAlchemyUnitOfWork) -> None:
    _source(uow)
    account_id = _account_id(uow)
    storage = _FakeStorage()
    svc = _service(storage)
    imp = svc.create_import(uow, account_id, SOURCE_NAME, "takeout")
    svc.complete_import(uow, account_id, imp.id, [_entry()])

    svc.delete_import(uow, account_id, imp.id)

    assert storage.deleted == [f"imports/{imp.id}/a.json"]
    with pytest.raises(ImportNotFoundError):
        svc.get_import(uow, account_id, imp.id)


def test_delete_import_unknown_id(uow: SqlAlchemyUnitOfWork) -> None:
    account_id = _account_id(uow)
    with pytest.raises(ImportNotFoundError):
        _service().delete_import(uow, account_id, uuid.uuid4())


def test_delete_import_deletes_objects_before_rows(uow: SqlAlchemyUnitOfWork) -> None:
    _source(uow)
    account_id = _account_id(uow)
    storage = _FakeStorage()
    svc = _service(storage)
    imp = svc.create_import(uow, account_id, SOURCE_NAME, "takeout")
    svc.complete_import(uow, account_id, imp.id, [_entry()])

    calls: list[str] = []

    def on_delete(keys: Sequence[str]) -> None:
        calls.append("objects")
        assert uow.imports.get(imp.id) is not None

    storage.on_delete = on_delete

    svc.delete_import(uow, account_id, imp.id)

    assert calls == ["objects"]


def test_create_import_requires_source(uow: SqlAlchemyUnitOfWork) -> None:
    from rosalind.application.errors import SourceNotFoundError

    account_id = _account_id(uow)
    with pytest.raises(SourceNotFoundError):
        composition.source_service.resolve_source(uow, account_id, "does-not-exist")
