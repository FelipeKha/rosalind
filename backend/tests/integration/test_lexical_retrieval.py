"""Integration tests for lexical (BM25) retrieval against real Postgres + pg_search.

These run on the ParadeDB image via the migrated engine, so they exercise the
real ``chunk_bm25_idx`` created by migration 0018. Scope confinement, filter
semantics, pushdown/overfetch reporting, and the ``exhausted`` flag are the
correctness surface; the adversarial deep-match test guards against any
top-k-then-filter recall loss.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.search.lexical import ParadeDbLexicalRetriever
from rosalind.application.search import (
    Direction,
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
from rosalind.application.search.plan import Budgets

_SENT_AT = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _retriever(engine: Engine) -> ParadeDbLexicalRetriever:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return ParadeDbLexicalRetriever(factory)


def _plan(
    source_account_ids,
    *,
    lexical_k: int = 50,
    filters: ResolvedFilters | None = None,
    terms: tuple[str, ...] = ("roof",),
    phrases: tuple[str, ...] = (),
) -> SearchPlan:
    account_id = uuid.uuid4()
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(
            account_id=account_id, source_account_ids=frozenset(source_account_ids)
        ),
        filters=filters or ResolvedFilters(),
        resolved_entities=(),
        query=PreparedQuery(lexical=LexicalQuery(terms=terms, phrases=phrases)),
        strategy=SearchStrategy.RANKED,
        mode_requested=SearchMode.LEXICAL,
        mode_effective=SearchMode.LEXICAL,
        presentation=Presentation(
            sort=SortOrder.RELEVANCE,
            group_by=GroupBy.MESSAGE,
            view=ResultView.SNIPPET,
            limit=10,
        ),
        budgets=Budgets(
            lexical_k=lexical_k,
            semantic_k=50,
            fused_k=40,
            rerank_k=30,
            window_k=25,
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=None,
        ),
    )


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
    email,
    *,
    text="roof quote slate replacement",
    sender="mike@turnerroofing.com",
    recipients=(),
    participants=(),
    tags=(),
    direction="received",
    has_attachment=False,
    is_trash_or_spam=False,
    language="en",
    sent_at=_SENT_AT,
    thread_id=None,
) -> models.Chunk:
    chunk = models.Chunk(
        id=uuid.uuid4(),
        email_id=email.id,
        thread_id=thread_id,
        chunk_kind="email_body",
        seq=0,
        text_for_display=text,
        text_for_index=text,
        text_sha256="abc",
        language=language,
        index_version="v1",
        source_account_id=source.id,
        source_account_num=source.num,
        sent_at=sent_at,
        sender_handle=sender,
        recipient_handles=list(recipients),
        participant_handles=list(participants),
        direction=direction,
        has_attachment=has_attachment,
        is_trash_or_spam=is_trash_or_spam,
        tags=list(tags),
        meta={},
    )
    db_session.add(chunk)
    return chunk


def _run(retriever, plan):
    return asyncio.run(retriever.retrieve(plan))


def _ids(result):
    return [hit.chunk_id for hit in result.hits]


def test_basic_match_returns_hit_with_score_and_rank(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    email = _email(migrated_db_session, source, "a@x")
    chunk = _chunk(migrated_db_session, source, email, text="roof quote slate")
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}))

    assert _ids(result) == [chunk.id]
    assert result.hits[0].rank == 1
    assert result.hits[0].score > 0
    assert result.hits[0].email_id == email.id
    assert result.exhausted is True


def test_rank_is_1_based_and_score_ordered(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    emails = [_email(migrated_db_session, source, f"m{i}@x") for i in range(3)]
    chunks = [
        _chunk(migrated_db_session, source, emails[0], text="roof roof roof roof roof"),
        _chunk(migrated_db_session, source, emails[1], text="roof roof"),
        _chunk(migrated_db_session, source, emails[2], text="roof"),
    ]
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, terms=("roof",)))

    assert [hit.rank for hit in result.hits] == [1, 2, 3]
    scores = [hit.score for hit in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert result.hits[0].chunk_id == chunks[0].id


def test_zero_results_are_exhausted(migrated_engine, migrated_db_session) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    email = _email(migrated_db_session, source, "a@x")
    _chunk(migrated_db_session, source, email, text="holiday in spain")
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, terms=("roof",)))

    assert result.hits == ()
    assert result.exhausted is True


def test_scope_always_applied(migrated_engine, migrated_db_session) -> None:
    in_source = _source(migrated_db_session, None, "in-scope")
    out_source = _source(migrated_db_session, None, "out-of-scope")
    in_email = _email(migrated_db_session, in_source, "in@x")
    out_email = _email(migrated_db_session, out_source, "out@x")
    in_chunk = _chunk(migrated_db_session, in_source, in_email, text="roof quote")
    _chunk(migrated_db_session, out_source, out_email, text="roof quote")
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({in_source.id}))

    assert _ids(result) == [in_chunk.id]


def test_sender_filter_is_or_within_field(migrated_engine, migrated_db_session) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    e3 = _email(migrated_db_session, source, "e3@x")
    c1 = _chunk(migrated_db_session, source, e1, text="roof", sender="a@x.com")
    c2 = _chunk(migrated_db_session, source, e2, text="roof", sender="b@x.com")
    _chunk(migrated_db_session, source, e3, text="roof", sender="c@x.com")
    migrated_db_session.commit()

    filters = ResolvedFilters(senders=frozenset({"a@x.com", "b@x.com"}))
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert set(_ids(result)) == {c1.id, c2.id}


def test_tags_are_or_within_field(migrated_engine, migrated_db_session) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, text="roof", tags=("gmail:Projects",))
    c2 = _chunk(migrated_db_session, source, e2, text="roof", tags=("gmail:Inbox",))
    migrated_db_session.commit()

    filters = ResolvedFilters(tags_any=frozenset({"gmail:Projects", "gmail:Inbox"}))
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert set(_ids(result)) == {c1.id, c2.id}


def test_exclude_tags(migrated_engine, migrated_db_session) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, text="roof", tags=("gmail:Projects",))
    _chunk(migrated_db_session, source, e2, text="roof", tags=("gmail:Inbox",))
    migrated_db_session.commit()

    filters = ResolvedFilters(tags_exclude=frozenset({"gmail:Inbox"}))
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert _ids(result) == [c1.id]


def test_direction_filter(migrated_engine, migrated_db_session) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, text="roof", direction="sent")
    _chunk(migrated_db_session, source, e2, text="roof", direction="received")
    migrated_db_session.commit()

    filters = ResolvedFilters(direction=Direction.SENT)
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert _ids(result) == [c1.id]


def test_date_from_inclusive_and_before_exclusive(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    e3 = _email(migrated_db_session, source, "e3@x")
    from_ts = datetime(2026, 3, 10, tzinfo=UTC)
    before_ts = datetime(2026, 3, 20, tzinfo=UTC)
    c1 = _chunk(migrated_db_session, source, e1, text="roof", sent_at=from_ts)
    c2 = _chunk(
        migrated_db_session,
        source,
        e2,
        text="roof",
        sent_at=datetime(2026, 3, 15, tzinfo=UTC),
    )
    _chunk(migrated_db_session, source, e3, text="roof", sent_at=before_ts)
    migrated_db_session.commit()

    filters = ResolvedFilters(sent_from=from_ts, sent_before=before_ts)
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert set(_ids(result)) == {c1.id, c2.id}


def test_has_attachment_filter(migrated_engine, migrated_db_session) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, text="roof", has_attachment=True)
    _chunk(migrated_db_session, source, e2, text="roof", has_attachment=False)
    migrated_db_session.commit()

    filters = ResolvedFilters(has_attachment=True)
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert _ids(result) == [c1.id]


def test_language_filter(migrated_engine, migrated_db_session) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, text="roof", language="fr")
    _chunk(migrated_db_session, source, e2, text="roof", language="en")
    migrated_db_session.commit()

    filters = ResolvedFilters(languages=frozenset({"fr"}))
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert _ids(result) == [c1.id]


def test_thread_filter_is_overfetch_path(migrated_engine, migrated_db_session) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    thread_a = models.EmailThread(
        id=uuid.uuid4(), source_account_id=source.id, root_message_id="root"
    )
    thread_b = models.EmailThread(
        id=uuid.uuid4(), source_account_id=source.id, root_message_id="root2"
    )
    migrated_db_session.add_all([thread_a, thread_b])
    migrated_db_session.flush()
    e1 = _email(migrated_db_session, source, "e1@x", thread_id=thread_a.id)
    e2 = _email(migrated_db_session, source, "e2@x", thread_id=thread_b.id)
    c1 = _chunk(migrated_db_session, source, e1, text="roof", thread_id=thread_a.id)
    _chunk(migrated_db_session, source, e2, text="roof", thread_id=thread_b.id)
    migrated_db_session.commit()

    filters = ResolvedFilters(thread_of=e1.id, thread_id=thread_a.id)
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert _ids(result) == [c1.id]
    assert result.filter_path == "overfetch"


def test_trash_spam_excluded_by_default_and_included_on_request(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, text="roof", is_trash_or_spam=False)
    _chunk(migrated_db_session, source, e2, text="roof", is_trash_or_spam=True)
    migrated_db_session.commit()

    default = _run(_retriever(migrated_engine), _plan({source.id}))
    assert _ids(default) == [c1.id]

    included = _run(
        _retriever(migrated_engine),
        _plan({source.id}, filters=ResolvedFilters(include_trash_spam=True)),
    )
    assert len(included.hits) == 2


def test_filter_path_is_pushdown_without_overfetch_filters(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    email = _email(migrated_db_session, source, "e1@x")
    _chunk(migrated_db_session, source, email, text="roof", direction="sent")
    migrated_db_session.commit()

    filters = ResolvedFilters(direction=Direction.SENT)
    result = _run(_retriever(migrated_engine), _plan({source.id}, filters=filters))

    assert result.filter_path == "pushdown"


def test_overfetch_reports_exhausted_only_when_true(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session, None, "google-personal")
    for i in range(5):
        email = _email(migrated_db_session, source, f"e{i}@x")
        _chunk(migrated_db_session, source, email, text="roof", tags=("gmail:Inbox",))
    migrated_db_session.commit()

    filters = ResolvedFilters(tags_any=frozenset({"gmail:Inbox"}))
    result = _run(
        _retriever(migrated_engine),
        _plan({source.id}, lexical_k=2, filters=filters),
    )

    assert result.filter_path == "overfetch"
    assert len(result.hits) == 2
    assert result.exhausted is False


def test_overfetch_does_not_lose_deep_match(
    migrated_engine, migrated_db_session
) -> None:
    source = _source(migrated_db_session, None, "google-personal")

    for i in range(150):
        email = _email(migrated_db_session, source, f"noise{i}@x")
        _chunk(
            migrated_db_session,
            source,
            email,
            text="roof roof roof roof",
            tags=("gmail:Inbox",),
        )

    target_email = _email(migrated_db_session, source, "target@x")
    target = _chunk(
        migrated_db_session,
        source,
        target_email,
        text="roof " + " ".join(f"filler{i}" for i in range(60)),
        tags=("gmail:Projects",),
    )
    migrated_db_session.commit()

    filters = ResolvedFilters(tags_any=frozenset({"gmail:Projects"}))
    result = _run(
        _retriever(migrated_engine),
        _plan({source.id}, lexical_k=1, filters=filters),
    )

    assert _ids(result) == [target.id]
    assert result.exhausted is True


def test_backend_failure_propagates() -> None:
    engine = create_engine(
        "postgresql+psycopg://rosalind:rosalind@127.0.0.1:1/rosalind",
        connect_args={"connect_timeout": 1},
    )
    retriever = ParadeDbLexicalRetriever(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    with pytest.raises(OperationalError):
        _run(retriever, _plan({uuid.uuid4()}))
