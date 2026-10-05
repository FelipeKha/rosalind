import uuid
from collections.abc import Sequence
from typing import BinaryIO

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application import manifest
from rosalind.application.services.emails import EmailProcessingService
from tests._account import ensure_account

MBOX = (
    b"From alice@example.com Mon Sep 28 12:00:00 2026\n"
    b"Message-ID: <a@example.com>\n"
    b"From: alice@example.com\n"
    b"Subject: hello\n"
    b"\n"
    b"Body of the first message.\n"
    b"\n"
    b"From bob@example.com Mon Sep 28 12:01:00 2026\n"
    b"Message-ID: <b@example.com>\n"
    b"From: bob@example.com\n"
    b"Subject: re: hello\n"
    b"\n"
    b"Body of the second message.\n"
    b"\n"
)


class _FakeStorage:
    bucket = "test-bucket"

    def __init__(self, mbox: bytes, existing: set[str] | None = None) -> None:
        self.mbox = mbox
        self.existing = existing or set()
        self.puts: dict[str, bytes] = {}
        self.downloads: list[str] = []

    def delete_objects(self, keys: Sequence[str]) -> None:
        raise NotImplementedError

    def download(self, key: str, dest: BinaryIO) -> None:
        self.downloads.append(key)
        dest.write(self.mbox)

    def put(self, key: str, data: bytes) -> None:
        self.puts[key] = data

    def exists(self, key: str) -> bool:
        return key in self.existing


def _setup(
    uow: SqlAlchemyUnitOfWork,
    *,
    mbox: bytes = MBOX,
    path: str = "Mail/All Mail.mbox",
    format_: str = "mbox",
) -> tuple[uuid.UUID, uuid.UUID]:
    account_id = ensure_account(uow).id
    composition.source_service.create_source(
        uow, account_id, provider="google", name="google-personal"
    )
    import_ = composition.import_service.create_import(
        uow, account_id, "google-personal", "takeout"
    )
    entry = manifest.FileEntry(
        path=path, sha256="a" * 64, size=len(mbox), format=format_
    )
    composition.import_service.complete_import(uow, account_id, import_.id, [entry])
    return account_id, import_.id


def test_split_creates_records(uow: SqlAlchemyUnitOfWork) -> None:
    account_id, import_id = _setup(uow)
    storage = _FakeStorage(MBOX)
    service = EmailProcessingService(storage=storage)

    prepared = service.prepare(uow, account_id, import_id)
    events = list(service.run(uow, prepared))

    assert events[0].stage == "starting"
    assert events[-1].stage == "done"
    assert events[-1].processed == 2
    assert events[-1].created == 2
    assert events[-1].reused == 0
    assert events[-1].failed == 0

    records = uow.source_records.list_for_import(import_id)
    assert len(records) == 2
    assert {r.external_id for r in records} == {"<a@example.com>", "<b@example.com>"}
    assert all(r.resource_type == "gmail.message" for r in records)
    assert all(r.payload_uri is not None for r in records)
    assert all(r.payload is None for r in records)
    assert set(storage.puts) == {r.payload_uri for r in records}


def test_split_is_idempotent(uow: SqlAlchemyUnitOfWork) -> None:
    account_id, import_id = _setup(uow)
    storage = _FakeStorage(MBOX)
    service = EmailProcessingService(storage=storage)

    list(service.run(uow, service.prepare(uow, account_id, import_id)))

    storage.existing = set(storage.puts)
    storage.puts.clear()

    events = list(service.run(uow, service.prepare(uow, account_id, import_id)))
    assert events[-1].processed == 2
    assert events[-1].created == 0
    assert events[-1].reused == 2
    assert storage.puts == {}
    assert len(uow.source_records.list_for_import(import_id)) == 2


def test_split_missing_message_id_uses_fallback(uow: SqlAlchemyUnitOfWork) -> None:
    content = (
        b"From a@b.example Mon Sep 28 12:00:00 2026\nSubject: no message id\n\nbody\n\n"
    )
    account_id, import_id = _setup(uow, mbox=content)
    storage = _FakeStorage(content)
    service = EmailProcessingService(storage=storage)

    list(service.run(uow, service.prepare(uow, account_id, import_id)))

    (record,) = uow.source_records.list_for_import(import_id)
    assert record.external_id == f"no-message-id:{record.payload_sha256}"


def test_split_ignores_non_mbox_files(uow: SqlAlchemyUnitOfWork) -> None:
    account_id, import_id = _setup(
        uow, mbox=b"{}", path="Contacts/contacts.json", format_="json"
    )
    storage = _FakeStorage(b"{}")
    service = EmailProcessingService(storage=storage)

    prepared = service.prepare(uow, account_id, import_id)
    assert prepared.files == ()

    events = list(service.run(uow, prepared))
    assert events[-1].processed == 0
    assert uow.source_records.list_for_import(import_id) == []
