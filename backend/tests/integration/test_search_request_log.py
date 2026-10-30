"""Integration test: a search writes exactly one ``search.request_log`` row."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from rosalind.adapters.inbound.http.routes import search as search_route
from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.search.trace_log import flush_old_request_logs
from tests._account import ensure_account

_WHEN = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _source(db_session, account_id):
    source = models.SourceAccount(account_id=account_id, provider="google", name="g")
    db_session.add(source)
    db_session.flush()
    return source


def _email(db_session, source):
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source.id,
        message_id="a@x",
        message_id_synthetic=False,
        occurred_at=_WHEN,
        direction="received",
        subject="Roof quote",
        has_attachments=False,
        is_trash_or_spam=False,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.flush()
    return message


def _chunk(db_session, source, email):
    db_session.add(
        models.Chunk(
            id=uuid.uuid4(),
            email_id=email.id,
            thread_id=None,
            chunk_kind="email_body",
            seq=0,
            text_for_display="roof quote slate",
            text_for_index="roof quote slate",
            text_sha256="abc",
            language="en",
            index_version="v1",
            source_account_id=source.id,
            source_account_num=source.num,
            sent_at=_WHEN,
            sender_handle="mike@turnerroofing.com",
            recipient_handles=[],
            participant_handles=["mike@turnerroofing.com"],
            direction="received",
            has_attachment=False,
            is_trash_or_spam=False,
            tags=[],
            meta={},
        )
    )


def test_search_writes_request_log_row(
    migrated_engine: Engine,
    migrated_uow,
    migrated_db_session,
    migrated_api_client,
    monkeypatch,
) -> None:
    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id)
    email = _email(migrated_db_session, source)
    _chunk(migrated_db_session, source, email)
    migrated_db_session.commit()

    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(search_route, "SessionLocal", factory)

    response = migrated_api_client.post(
        "/search", json={"query": "roof", "mode": "lexical", "view": "metadata"}
    )
    assert response.status_code == 200, response.text

    rows = migrated_db_session.scalars(select(models.SearchRequestLog)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.account_id == account.id
    assert row.strategy == "ranked"
    assert row.result_count >= 1
    assert email.id in row.returned_item_ids
    # Content-free: no query text or addresses are stored.
    assert "roof" not in row.plan_fingerprint


def test_flush_old_request_logs_removes_rows(
    migrated_engine: Engine,
    migrated_uow,
    migrated_db_session,
    migrated_api_client,
    monkeypatch,
) -> None:
    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id)
    email = _email(migrated_db_session, source)
    _chunk(migrated_db_session, source, email)
    migrated_db_session.commit()

    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(search_route, "SessionLocal", factory)
    migrated_api_client.post("/search", json={"query": "roof", "mode": "lexical"})

    deleted = flush_old_request_logs(migrated_db_session, retention_days=0)
    migrated_db_session.commit()
    assert deleted == 1
    assert migrated_db_session.scalars(select(models.SearchRequestLog)).all() == []
