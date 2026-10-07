"""Integration tests for the assembly metadata adapters against real Postgres.

These verify the two outbound ports used by assembly: ``SearchResultDataPort``
(batch metadata fetch with scope re-check and text gating) and
``MessageListPort`` (keyset listing, one row per message).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, event
from sqlalchemy.orm import sessionmaker

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.search.list_retriever import (
    PostgresMessageListRetriever,
)
from rosalind.adapters.outbound.search.result_data import (
    PostgresSearchResultDataRepository,
)
from rosalind.application.search import (
    Budgets,
    FusionConfig,
    GroupBy,
    IndexVersions,
    LexicalQuery,
    PreparedQuery,
    Presentation,
    RequestContext,
    ResolvedFilters,
    ResultView,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SortOrder,
)
from tests._account import ensure_account

_WHEN = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _plan(source_account_ids: frozenset[uuid.UUID]) -> SearchPlan:
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(account_id=uuid.uuid4(), source_account_ids=source_account_ids),
        filters=ResolvedFilters(),
        resolved_entities=(),
        query=PreparedQuery(lexical=LexicalQuery(terms=("roof",))),
        strategy=SearchStrategy.RANKED,
        mode_requested=SearchMode.LEXICAL,
        mode_effective=SearchMode.LEXICAL,
        presentation=Presentation(
            sort=SortOrder.RELEVANCE,
            group_by=GroupBy.MESSAGE,
            view=ResultView.SNIPPET,
            limit=25,
        ),
        budgets=Budgets(
            lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=25
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=None,
        ),
        fusion=FusionConfig(),
    )


def _list_plan(source_account_ids: frozenset[uuid.UUID]) -> SearchPlan:
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(account_id=uuid.uuid4(), source_account_ids=source_account_ids),
        filters=ResolvedFilters(),
        resolved_entities=(),
        query=PreparedQuery(),
        strategy=SearchStrategy.LIST,
        mode_requested=SearchMode.LEXICAL,
        mode_effective=SearchMode.LEXICAL,
        presentation=Presentation(
            sort=SortOrder.DATE_DESC,
            group_by=GroupBy.MESSAGE,
            view=ResultView.METADATA,
            limit=25,
        ),
        budgets=Budgets(
            lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=25
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=None,
        ),
        fusion=FusionConfig(),
    )


def _source(db_session, account_id, name="google-personal"):
    source = models.SourceAccount(account_id=account_id, provider="google", name=name)
    db_session.add(source)
    db_session.flush()
    return source


def _email(db_session, source, message_id, *, subject="subject", thread_id=None):
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
        thread_id=thread_id,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.flush()
    return message


def _attachment(db_session, message, filename="quote.pdf"):
    attachment = models.EmailAttachment(
        id=uuid.uuid4(),
        message_id=message.id,
        filename=filename,
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        size=100,
        sha256="e5a1",
        disposition="attachment",
        storage_key="blobs/e5a1",
        part_index=0,
        status="present",
    )
    db_session.add(attachment)
    db_session.flush()
    return attachment


def _chunk(
    db_session,
    source,
    email_id,
    *,
    chunk_kind="email_body",
    seq=0,
    attachment_id=None,
    display_text="hello",
):
    db_session.add(
        models.Chunk(
            id=uuid.uuid4(),
            email_id=email_id,
            attachment_id=attachment_id,
            thread_id=None,
            chunk_kind=chunk_kind,
            seq=seq,
            text_for_display=display_text,
            text_for_index=display_text,
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
            has_attachment=chunk_kind == "attachment",
            is_trash_or_spam=False,
            tags=[],
            meta={},
        )
    )


def _result_data_repo(migrated_engine: Engine) -> PostgresSearchResultDataRepository:
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    return PostgresSearchResultDataRepository(factory)


def _list_repo(migrated_engine: Engine) -> PostgresMessageListRetriever:
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    return PostgresMessageListRetriever(factory)


def _count_queries(engine: Engine, fn):
    counter = {"n": 0}

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        return fn(), counter["n"]
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


def test_result_data_batch_is_a_single_query(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id)
    email = _email(migrated_db_session, source, "a@x", subject="Roof quote")
    attachment = _attachment(migrated_db_session, email, "quote-2026.pdf")
    for seq in range(24):
        _chunk(migrated_db_session, source, email.id, seq=seq)
    _chunk(
        migrated_db_session,
        source,
        email.id,
        chunk_kind="attachment",
        attachment_id=attachment.id,
        display_text="total $8,400",
    )
    migrated_db_session.commit()

    repo = _result_data_repo(migrated_engine)
    plan = _plan(frozenset({source.id}))
    chunk_ids = tuple(
        row[0]
        for row in migrated_db_session.query(models.Chunk.id)
        .filter(models.Chunk.source_account_id == source.id)
        .all()
    )

    (data, queries) = _count_queries(
        migrated_engine,
        lambda: asyncio.run(repo.get_results(plan, chunk_ids, include_text=True)),
    )
    # scope resolution + one metadata fetch, never one query per chunk.
    assert queries == 2
    assert len(data) == len(chunk_ids)
    by_kind = {d.chunk_kind.value: d for d in data}
    assert by_kind["email_body"].subject == "Roof quote"
    attachment_data = by_kind["attachment"]
    assert attachment_data.attachment_name == "quote-2026.pdf"
    assert attachment_data.display_text == "total $8,400"


def test_result_data_metadata_view_does_not_load_text(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id)
    email = _email(migrated_db_session, source, "a@x")
    _chunk(migrated_db_session, source, email.id, display_text="secret text")
    migrated_db_session.commit()

    repo = _result_data_repo(migrated_engine)
    plan = _plan(frozenset({source.id}))
    chunk_id = migrated_db_session.query(models.Chunk.id).scalar()

    data = asyncio.run(repo.get_results(plan, (chunk_id,), include_text=False))
    assert data[0].display_text is None


def test_result_data_rechecks_scope(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    account = ensure_account(migrated_uow)
    in_source = _source(migrated_db_session, account.id, "in-scope")
    out_source = _source(migrated_db_session, None, "out-scope")
    email = _email(migrated_db_session, in_source, "a@x")
    _chunk(migrated_db_session, in_source, email.id)
    out_email = _email(migrated_db_session, out_source, "b@x")
    _chunk(migrated_db_session, out_source, out_email.id)
    migrated_db_session.commit()

    out_chunk = (
        migrated_db_session.query(models.Chunk)
        .filter(models.Chunk.source_account_id == out_source.id)
        .one()
    )
    in_chunk = (
        migrated_db_session.query(models.Chunk)
        .filter(models.Chunk.source_account_id == in_source.id)
        .one()
    )

    repo = _result_data_repo(migrated_engine)
    plan = _plan(frozenset({in_source.id}))
    data = asyncio.run(
        repo.get_results(plan, (in_chunk.id, out_chunk.id), include_text=False)
    )
    assert [d.chunk_id for d in data] == [in_chunk.id]


def test_list_retriever_one_row_per_message_and_total(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id)
    email_a = _email(migrated_db_session, source, "a@x", subject="A")
    email_b = _email(migrated_db_session, source, "b@x", subject="B")
    # A has two email_body chunks (seq 0 and 1); only seq 0 should be listed.
    _chunk(migrated_db_session, source, email_a.id, seq=0)
    _chunk(migrated_db_session, source, email_a.id, seq=1)
    _chunk(migrated_db_session, source, email_b.id, seq=0)
    migrated_db_session.commit()

    repo = _list_repo(migrated_engine)
    plan = _list_plan(frozenset({source.id}))
    listed = asyncio.run(repo.list(plan))

    assert listed.total == 2
    assert [d.subject for d in listed.items] == ["A", "B"]
