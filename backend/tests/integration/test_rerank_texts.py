"""Integration tests for the rerank chunk-text fetcher against real Postgres.

Verifies the one-query fetch, ordered restoration, column selection per text
mode, and that a missing chunk id is dropped rather than raised.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.search.chunk_text import PostgresChunkTextRepository
from rosalind.application.search import RerankTextMode

_SENT_AT = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _repository(engine: Engine) -> PostgresChunkTextRepository:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return PostgresChunkTextRepository(factory)


def _source(db_session):
    source = models.SourceAccount(account_id=None, provider="google", name="google")
    db_session.add(source)
    db_session.flush()
    return source


def _email(db_session, source):
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source.id,
        message_id=f"{uuid.uuid4()}@x",
        message_id_synthetic=False,
        occurred_at=_SENT_AT,
        direction="received",
        subject="subject",
        has_attachments=False,
        is_trash_or_spam=False,
        thread_id=None,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.flush()
    return message


def _chunk(
    db_session, source, email, *, index_text, display_text, seq=0
) -> models.Chunk:
    chunk = models.Chunk(
        id=uuid.uuid4(),
        email_id=email.id,
        thread_id=None,
        chunk_kind="email_body",
        seq=seq,
        text_for_display=display_text,
        text_for_index=index_text,
        text_sha256="abc",
        language="en",
        index_version="v1",
        source_account_id=source.id,
        source_account_num=source.num,
        sent_at=_SENT_AT,
        sender_handle="mike@turnerroofing.com",
        recipient_handles=[],
        participant_handles=["mike@turnerroofing.com"],
        direction="received",
        has_attachment=False,
        is_trash_or_spam=False,
        tags=[],
        meta={},
    )
    db_session.add(chunk)
    return chunk


def _run(repo, chunk_ids, mode):
    return asyncio.run(repo.get_rerank_texts(chunk_ids, mode))


def test_fetch_restores_order_and_drops_missing(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session)
    email = _email(migrated_db_session, source)
    first = _chunk(
        migrated_db_session, source, email, index_text="first", display_text="d1"
    )
    second = _chunk(
        migrated_db_session,
        source,
        email,
        index_text="second",
        display_text="d2",
        seq=1,
    )
    migrated_db_session.commit()

    repo = _repository(migrated_engine)
    result = _run(repo, (second.id, first.id, uuid.uuid4()), RerankTextMode.INDEX)

    assert [item.chunk_id for item in result] == [second.id, first.id]
    assert [item.text for item in result] == ["second", "first"]


def test_display_mode_selects_display_column(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session)
    email = _email(migrated_db_session, source)
    chunk = _chunk(
        migrated_db_session, source, email, index_text="IDX", display_text="DSP"
    )
    migrated_db_session.commit()

    repo = _repository(migrated_engine)
    result = _run(repo, (chunk.id,), RerankTextMode.DISPLAY)

    assert [item.text for item in result] == ["DSP"]


def test_empty_ids_returns_nothing(migrated_engine) -> None:
    repo = _repository(migrated_engine)
    assert _run(repo, (), RerankTextMode.INDEX) == ()
