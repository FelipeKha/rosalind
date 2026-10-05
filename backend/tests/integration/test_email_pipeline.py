import uuid
from collections.abc import Sequence
from typing import BinaryIO

from sqlalchemy import select, update

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application import manifest
from rosalind.application.canonicalization.email_message import (
    EmailCanonicalizationService,
)
from rosalind.application.services.emails import EmailProcessingService
from tests._account import ensure_account

SELF_EMAIL = "alex@example.com"

MBOX = (
    b"From alice@example.com Mon Sep 28 12:00:00 2026\n"
    b"Message-ID: <a@example.com>\n"
    b"From: Alice <alice@example.com>\n"
    b"To: Alex <alex@example.com>\n"
    b"Subject: hello\n"
    b"\n"
    b"Body of the first message.\n"
    b"\n"
    b"From bob@example.com Mon Sep 28 12:01:00 2026\n"
    b"Message-ID: <b@example.com>\n"
    b"From: Bob <bob@example.com>\n"
    b"To: Alex <alex@example.com>\n"
    b"Subject: re: hello\n"
    b"\n"
    b"Body of the second message.\n"
    b"\n"
)


class _FakeStorage:
    bucket = "test-bucket"

    def __init__(self, mbox: bytes, objects: dict[str, bytes] | None = None) -> None:
        self.mbox = mbox
        self.objects: dict[str, bytes] = dict(objects or {})
        self.puts: list[str] = []
        self.downloads: list[str] = []

    def delete_objects(self, keys: Sequence[str]) -> None:
        raise NotImplementedError

    def download(self, key: str, dest: BinaryIO) -> None:
        self.downloads.append(key)
        dest.write(self.objects.get(key, self.mbox))

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data
        self.puts.append(key)

    def exists(self, key: str) -> bool:
        return key in self.objects


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


def _service(storage: _FakeStorage) -> EmailProcessingService:
    return EmailProcessingService(
        storage=storage, canonicalizer=EmailCanonicalizationService()
    )


def _make_self_person(db_session, account_id: uuid.UUID, email: str) -> uuid.UUID:
    person = models.Person()
    db_session.add(person)
    db_session.flush()
    db_session.add(
        models.PersonEmail(
            person_id=person.id,
            email=email,
            email_normalized=email.lower(),
            is_primary=True,
            is_verified=False,
        )
    )
    db_session.execute(
        update(models.Account)
        .where(models.Account.id == account_id)
        .values(self_person_id=person.id)
    )
    db_session.commit()
    return person.id


def test_split_and_canonicalize(uow: SqlAlchemyUnitOfWork, db_session) -> None:
    account_id, import_id = _setup(uow)
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(MBOX)
    service = _service(storage)

    events = list(service.run(uow, service.prepare(uow, account_id, import_id)))

    assert events[0].stage == "starting"
    assert events[-1].stage == "canonicalized"
    assert events[-1].processed == 2
    assert events[-1].created == 2
    assert events[-1].failed == 0

    messages = db_session.scalars(select(models.EmailMessage)).all()
    assert {m.message_id for m in messages} == {"a@example.com", "b@example.com"}
    assert all(m.direction == "received" for m in messages)
    assert all(m.source_account_id is not None for m in messages)

    participants = db_session.scalars(select(models.EmailParticipant)).all()
    assert {p.addr for p in participants} == {
        "alice@example.com",
        "bob@example.com",
        "alex@example.com",
    }

    threads = db_session.scalars(select(models.EmailThread)).all()
    assert len(threads) == 2

    observations = db_session.scalars(select(models.EmailMessageObservation)).all()
    assert len(observations) == 2


def test_canonicalize_is_idempotent(uow: SqlAlchemyUnitOfWork, db_session) -> None:
    account_id, import_id = _setup(uow)
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(MBOX)
    service = _service(storage)

    list(service.run(uow, service.prepare(uow, account_id, import_id)))
    puts_after_first = len(storage.puts)

    events = list(service.run(uow, service.prepare(uow, account_id, import_id)))
    assert events[-1].stage == "canonicalized"
    assert events[-1].created == 0
    assert events[-1].reused == 2
    assert len(storage.puts) == puts_after_first

    assert len(db_session.scalars(select(models.EmailMessage)).all()) == 2


def test_missing_message_id_uses_synthetic_id(
    uow: SqlAlchemyUnitOfWork, db_session
) -> None:
    content = (
        b"From a@b.example Mon Sep 28 12:00:00 2026\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: no message id\n"
        b"\n"
        b"body\n"
        b"\n"
    )
    account_id, import_id = _setup(uow, mbox=content)
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(content)
    service = _service(storage)

    list(service.run(uow, service.prepare(uow, account_id, import_id)))

    (message,) = db_session.scalars(select(models.EmailMessage)).all()
    assert message.message_id_synthetic is True
    assert message.message_id.startswith("no-message-id:")


def test_second_observation_replaces_tags(
    uow: SqlAlchemyUnitOfWork, db_session
) -> None:
    first = (
        b"From alice@example.com Mon Sep 28 12:00:00 2026\n"
        b"Message-ID: <dup@example.com>\n"
        b"From: Alice <alice@example.com>\n"
        b"To: Alex <alex@example.com>\n"
        b"X-Gmail-Labels: Inbox,Projects\n"
        b"Subject: labels\n"
        b"\n"
        b"body\n"
        b"\n"
    )
    second = (
        b"From alice@example.com Mon Sep 28 12:00:00 2026\n"
        b"Message-ID: <dup@example.com>\n"
        b"From: Alice <alice@example.com>\n"
        b"To: Alex <alex@example.com>\n"
        b"X-Gmail-Labels: Archive\n"
        b"Subject: labels\n"
        b"\n"
        b"body\n"
        b"\n"
    )
    account_id, import_id = _setup(uow, mbox=first)
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(first)
    service = _service(storage)

    list(service.run(uow, service.prepare(uow, account_id, import_id)))

    # A later archive with the same Message-ID but changed labels.
    second_storage = _FakeStorage(second)
    second_import = composition.import_service.create_import(
        uow, account_id, "google-personal", "takeout"
    )
    entry = manifest.FileEntry(
        path="Mail/All Mail.mbox", sha256="b" * 64, size=len(second), format="mbox"
    )
    composition.import_service.complete_import(
        uow, account_id, second_import.id, [entry]
    )
    list(
        _service(second_storage).run(
            uow, _service(second_storage).prepare(uow, account_id, second_import.id)
        )
    )

    db_session.scalars(select(models.EmailMessage)).all()
    tags = {t.tag for t in db_session.scalars(select(models.EmailTag)).all()}
    assert tags == {"gmail:Archive"}
    assert len(db_session.scalars(select(models.EmailMessageObservation)).all()) == 2


def test_reply_before_root_same_thread(uow: SqlAlchemyUnitOfWork, db_session) -> None:
    reply = (
        b"From bob@example.com Mon Sep 28 12:01:00 2026\n"
        b"Message-ID: <reply@example.com>\n"
        b"In-Reply-To: <root@example.com>\n"
        b"From: Bob <bob@example.com>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: Re: hi\n"
        b"\n"
        b"reply body\n"
        b"\n"
        b"From root@example.com Mon Sep 28 12:00:00 2026\n"
        b"Message-ID: <root@example.com>\n"
        b"From: Root <root@example.com>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: hi\n"
        b"\n"
        b"root body\n"
        b"\n"
    )
    account_id, import_id = _setup(uow, mbox=reply)
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(reply)
    service = _service(storage)

    list(service.run(uow, service.prepare(uow, account_id, import_id)))

    messages = db_session.scalars(select(models.EmailMessage)).all()
    assert len({m.thread_id for m in messages}) == 1


def test_canonicalize_requires_self_handles(uow: SqlAlchemyUnitOfWork) -> None:
    account_id, import_id = _setup(uow)
    storage = _FakeStorage(MBOX)
    service = _service(storage)

    events = list(service.run(uow, service.prepare(uow, account_id, import_id)))

    assert events[-1].stage == "error"
    assert "self" in (events[-1].message or "")


def test_split_ignores_non_mbox_files(uow: SqlAlchemyUnitOfWork, db_session) -> None:
    account_id, import_id = _setup(
        uow, mbox=b"{}", path="Contacts/contacts.json", format_="json"
    )
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(b"{}")
    service = _service(storage)

    prepared = service.prepare(uow, account_id, import_id)
    assert prepared.files == ()

    events = list(service.run(uow, prepared))
    assert events[-1].stage == "canonicalized"
    assert events[-1].processed == 0
    assert uow.source_records.list_for_import(import_id) == []
