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
from rosalind.application.services.email_reconciliation import (
    EmailReconciliationService,
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
        storage=storage,
        canonicalizer=EmailCanonicalizationService(),
        reconciler=EmailReconciliationService(),
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
    canonicalized = next(event for event in events if event.stage == "canonicalized")
    assert canonicalized.processed == 2
    assert canonicalized.created == 2
    assert canonicalized.failed == 0
    assert events[-1].stage == "reconciled"

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
    canonicalized = next(event for event in events if event.stage == "canonicalized")
    assert canonicalized.created == 0
    assert canonicalized.reused == 2
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

    (message,) = db_session.scalars(select(models.EmailMessage)).all()
    updated_before = message.updated_at

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

    # A tag-only re-observation still bumps updated_at, which is the chunk
    # work finder's signal to refresh denormalized filter columns.
    (message_after,) = db_session.scalars(select(models.EmailMessage)).all()
    assert message_after.updated_at > updated_before


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
    canonicalized = next(event for event in events if event.stage == "canonicalized")
    assert canonicalized.processed == 0
    assert events[-1].stage == "reconciled"
    assert uow.source_records.list_for_import(import_id) == []


def test_reconcile_heals_truncated_references(
    uow: SqlAlchemyUnitOfWork, db_session
) -> None:
    mbox = (
        b"From root@x Mon Sep 28 12:00:00 2026\n"
        b"Message-ID: <root@x>\n"
        b"From: Root <root@x>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: hi\n"
        b"\n"
        b"root body\n"
        b"\n"
        b"From a@x Mon Sep 28 12:01:00 2026\n"
        b"Message-ID: <a@x>\n"
        b"In-Reply-To: <root@x>\n"
        b"References: <root@x>\n"
        b"From: A <a@x>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: Re: hi\n"
        b"\n"
        b"a body\n"
        b"\n"
        b"From c@x Mon Sep 28 12:02:00 2026\n"
        b"Message-ID: <c@x>\n"
        b"References: <a@x>\n"
        b"From: C <c@x>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: Re: hi\n"
        b"\n"
        b"c body\n"
        b"\n"
    )
    account_id, import_id = _setup(uow, mbox=mbox)
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(mbox)
    service = _service(storage)

    events = list(service.run(uow, service.prepare(uow, account_id, import_id)))

    assert events[-1].stage == "reconciled"
    assert events[-1].details == {
        "threads_created": 0,
        "threads_removed": 1,
        "messages_reassigned": 1,
    }

    messages = db_session.scalars(select(models.EmailMessage)).all()
    assert len({m.thread_id for m in messages}) == 1
    reassigned = {m.message_id for m in messages if m.thread_changed_at is not None}
    assert reassigned == {"c@x"}
    assert len(db_session.scalars(select(models.EmailThread)).all()) == 1


def test_reconcile_bridges_separate_threads(
    uow: SqlAlchemyUnitOfWork, db_session
) -> None:
    mbox = (
        b"From x@x Mon Sep 28 12:00:00 2026\n"
        b"Message-ID: <x@x>\n"
        b"From: X <x@x>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: one\n"
        b"\n"
        b"x body\n"
        b"\n"
        b"From z@x Mon Sep 28 12:01:00 2026\n"
        b"Message-ID: <z@x>\n"
        b"From: Z <z@x>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: two\n"
        b"\n"
        b"z body\n"
        b"\n"
        b"From m@x Mon Sep 28 12:02:00 2026\n"
        b"Message-ID: <m@x>\n"
        b"References: <x@x> <z@x>\n"
        b"From: M <m@x>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: bridge\n"
        b"\n"
        b"m body\n"
        b"\n"
    )
    account_id, import_id = _setup(uow, mbox=mbox)
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(mbox)
    service = _service(storage)

    list(service.run(uow, service.prepare(uow, account_id, import_id)))

    messages = db_session.scalars(select(models.EmailMessage)).all()
    assert len({m.thread_id for m in messages}) == 1


def test_reconcile_is_idempotent(uow: SqlAlchemyUnitOfWork, db_session) -> None:
    mbox = (
        b"From root@x Mon Sep 28 12:00:00 2026\n"
        b"Message-ID: <root@x>\n"
        b"From: Root <root@x>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: hi\n"
        b"\n"
        b"root body\n"
        b"\n"
        b"From a@x Mon Sep 28 12:01:00 2026\n"
        b"Message-ID: <a@x>\n"
        b"References: <root@x>\n"
        b"From: A <a@x>\n"
        b"To: Alex <alex@example.com>\n"
        b"Subject: Re: hi\n"
        b"\n"
        b"a body\n"
        b"\n"
    )
    account_id, import_id = _setup(uow, mbox=mbox)
    _make_self_person(db_session, account_id, SELF_EMAIL)
    storage = _FakeStorage(mbox)
    service = _service(storage)

    first = list(service.run(uow, service.prepare(uow, account_id, import_id)))
    assert first[-1].stage == "reconciled"

    second = list(service.run(uow, service.prepare(uow, account_id, import_id)))
    assert second[-1].stage == "reconciled"
    assert second[-1].details == {
        "threads_created": 0,
        "threads_removed": 0,
        "messages_reassigned": 0,
    }
