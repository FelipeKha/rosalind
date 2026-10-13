"""Integration tests for the REST ``POST /search`` endpoint.

The route is a thin adapter over ``SearchService`` (the same service the MCP
tool uses), so these tests focus on transport mapping: request validation,
scope resolution through the authenticated account, and response shape. They
exercise real lexical retrieval against the migrated ParadeDB/pg_search schema.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from rosalind.adapters.inbound.http.routes import search as search_route
from rosalind.adapters.outbound.persistence import models
from tests._account import ensure_account

_WHEN = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _source(db_session, account_id, name="google-personal"):
    source = models.SourceAccount(account_id=account_id, provider="google", name=name)
    db_session.add(source)
    db_session.flush()
    return source


def _email(db_session, source, message_id, *, subject="subject"):
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source.id,
        message_id=message_id,
        message_id_synthetic=False,
        occurred_at=_WHEN,
        direction="received",
        subject=subject,
        has_attachments=False,
        is_trash_or_spam=False,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.flush()
    return message


def _chunk(db_session, source, email, *, text="roof quote slate replacement"):
    db_session.add(
        models.Chunk(
            id=uuid.uuid4(),
            email_id=email.id,
            thread_id=None,
            chunk_kind="email_body",
            seq=0,
            text_for_display=text,
            text_for_index=text,
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


def _point_session_local_at(engine: Engine, monkeypatch) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(search_route, "SessionLocal", factory)


def test_lexical_search_returns_matching_message(
    migrated_engine, migrated_uow, migrated_db_session, migrated_api_client, monkeypatch
) -> None:
    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id)
    email = _email(migrated_db_session, source, "a@x", subject="Roof quote")
    _chunk(migrated_db_session, source, email)
    migrated_db_session.commit()

    _point_session_local_at(migrated_engine, monkeypatch)

    response = migrated_api_client.post(
        "/search",
        json={"query": "roof", "mode": "lexical", "view": "metadata"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode_effective"] == "lexical"
    assert body["results"], body
    assert body["results"][0]["item_id"] == str(email.id)
    assert body["results"][0]["subject"] == "Roof quote"


def test_empty_scope_short_circuits(
    migrated_engine, migrated_uow, migrated_api_client, monkeypatch
) -> None:
    ensure_account(migrated_uow)
    _point_session_local_at(migrated_engine, monkeypatch)

    response = migrated_api_client.post("/search", json={"query": "roof"})

    assert response.status_code == 200, response.text
    assert response.json()["short_circuit"] == "empty_scope"


def test_malformed_request_is_rejected(
    migrated_engine, migrated_uow, migrated_api_client, monkeypatch
) -> None:
    ensure_account(migrated_uow)
    _point_session_local_at(migrated_engine, monkeypatch)

    response = migrated_api_client.post("/search", json={})

    assert response.status_code == 422
    body = response.json()
    assert "at least one of query, keywords, or a filter" in body["detail"]
