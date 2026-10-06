"""Integration tests for the read-only search adapters against real Postgres.

These verify scope confinement and the corpus metadata the Prepare step relies
on: only source accounts owned by the account are returned, and entity/thread
resolution is bounded by the effective scope.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.search.search_repository import PostgresSearchRepository
from tests._account import ensure_account

_SENT_AT = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _source(db_session, account_id, name):
    source = models.SourceAccount(account_id=account_id, provider="google", name=name)
    db_session.add(source)
    db_session.flush()
    return source


def _email(db_session, source, message_id, *, thread_id=None):
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source.id,
        message_id=message_id,
        message_id_synthetic=False,
        occurred_at=_SENT_AT,
        direction="received",
        subject="subject",
        has_attachments=False,
        is_trash_or_spam=False,
        thread_id=thread_id,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.flush()
    return message


def _chunk(
    db_session,
    source,
    email_id,
    *,
    tags=("gmail:Projects",),
    handles=("alex@example.com",),
    language="en",
):
    db_session.add(
        models.Chunk(
            id=uuid.uuid4(),
            email_id=email_id,
            chunk_kind="email_body",
            seq=0,
            text_for_display="hello",
            text_for_index="hello",
            text_sha256="abc",
            language=language,
            index_version="v1",
            source_account_id=source.id,
            source_account_num=source.num,
            sent_at=_SENT_AT,
            sender_handle="",
            recipient_handles=[],
            participant_handles=list(handles),
            direction="received",
            has_attachment=False,
            is_trash_or_spam=False,
            tags=list(tags),
            meta={},
        )
    )


def _person_with_email(db_session, source, email):
    person = models.Person(id=uuid.uuid4())
    db_session.add(person)
    db_session.flush()
    db_session.add(
        models.PersonEmail(
            id=uuid.uuid4(),
            person_id=person.id,
            email=email,
            email_normalized=email.lower(),
            is_primary=True,
            is_verified=False,
        )
    )
    db_session.add(
        models.SourceIdentity(
            id=uuid.uuid4(),
            person_id=person.id,
            source_account_id=source.id,
            source_type="google",
            external_id=email,
            resource_name=f"people/{email}",
        )
    )
    return person


def _repo(migrated_engine: Engine) -> PostgresSearchRepository:
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    return PostgresSearchRepository(factory)


def test_scope_is_account_owned_source_accounts(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "google-personal")
    other = _source(migrated_db_session, None, "other-account")
    migrated_db_session.commit()

    repo = _repo(migrated_engine)
    scope = asyncio.run(repo.get_scope(account.id))
    assert source.id in scope
    assert other.id not in scope


def test_metadata_reflects_corpus(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "google-personal")
    email = _email(migrated_db_session, source, "a@x")
    _chunk(
        migrated_db_session,
        source,
        email.id,
        tags=("gmail:Projects",),
        handles=("mike@turnerroofing.com",),
        language="en",
    )
    migrated_db_session.commit()

    repo = _repo(migrated_engine)
    metadata = asyncio.run(repo.get_metadata(frozenset({source.id})))
    assert "gmail:Projects" in metadata.known_tags
    assert "mike@turnerroofing.com" in metadata.known_handles
    assert "en" in metadata.known_languages
    assert metadata.min_sent_at == _SENT_AT


def test_thread_resolution_is_scope_confined(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    account = ensure_account(migrated_uow)
    in_source = _source(migrated_db_session, account.id, "in-scope")
    out_source = _source(migrated_db_session, None, "out-of-scope")

    thread = models.EmailThread(
        id=uuid.uuid4(), source_account_id=in_source.id, root_message_id="root"
    )
    migrated_db_session.add(thread)
    migrated_db_session.flush()

    in_message = _email(migrated_db_session, in_source, "in@x", thread_id=thread.id)
    out_message = _email(migrated_db_session, out_source, "out@x", thread_id=thread.id)
    migrated_db_session.commit()

    repo = _repo(migrated_engine)
    from rosalind.application.search import Scope

    scope = Scope(account_id=account.id, source_account_ids=frozenset({in_source.id}))
    assert asyncio.run(repo.resolve_thread(scope, in_message.id)) == thread.id
    assert asyncio.run(repo.resolve_thread(scope, out_message.id)) is None


def test_entity_resolution_is_scope_confined(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    account = ensure_account(migrated_uow)
    in_source = _source(migrated_db_session, account.id, "in-scope")
    out_source = _source(migrated_db_session, None, "out-of-scope")

    in_person = _person_with_email(migrated_db_session, in_source, "Alex@Example.com")
    out_person = _person_with_email(migrated_db_session, out_source, "Zoe@Example.com")

    migrated_uow.accounts.set_self_person_id(account.id, in_person.id)
    migrated_db_session.commit()

    repo = _repo(migrated_engine)
    from rosalind.application.search import Scope

    scope = Scope(account_id=account.id, source_account_ids=frozenset({in_source.id}))

    resolved = asyncio.run(
        repo.resolve(scope, (str(in_person.id), str(out_person.id), "me"))
    )
    by_requested = {entity.requested: entity for entity in resolved}

    assert by_requested[str(in_person.id)].handles == frozenset({"alex@example.com"})
    assert by_requested[str(out_person.id)].handles == frozenset()
    assert by_requested["me"].handles == frozenset({"alex@example.com"})
