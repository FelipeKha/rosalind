"""Integration tests for semantic (vector) retrieval against real Postgres + pgvector.

These run on the migrated engine, exercising the real ``chunk_emb_bge_m3_v1_hnsw``
HNSW index created by migration 0019 (and the exact path when the index is absent
or the policy asks for it). Scope confinement, the freshness rule (stale vectors
never returned), the ``complete`` / ``scan_limit_hit`` contract, and the exact/ANN
split are the correctness surface.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import sessionmaker

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.search.semantic import (
    PgVectorSemanticRetriever,
    SemanticRetrievalConfig,
)
from rosalind.application.search import (
    Direction,
    GroupBy,
    IndexVersions,
    PreparedQuery,
    Presentation,
    QueryVector,
    RequestContext,
    ResolvedFilters,
    ResultView,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SemanticRetrievalError,
    SortOrder,
)
from rosalind.application.search.plan import Budgets, PlanHints

_SENT_AT = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)
_DIM = 1024
_MODEL = "BAAI/bge-m3"
_VERSION = "bge_m3_v1"


def _vec(value: float, index: int) -> list[float]:
    v = [0.0] * _DIM
    v[index] = value
    return v


QUERY = _vec(
    1.0, 0
)  # cosine distance 0 to itself, 1 to an orthogonal basis, 2 to -itself


def _near(i: int) -> list[float]:
    """A distinct vector very close to ``QUERY`` (so distinct near chunks still
    rank above the orthogonal "far" chunks, but are never identical)."""
    eps = 0.0001 * (i + 1)
    v = [1.0] + [0.0] * (_DIM - 1)
    v[1] = eps
    norm = math.sqrt(1.0 + eps * eps)
    return [x / norm for x in v]


def _retriever(engine: Engine, config: SemanticRetrievalConfig | None = None):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return PgVectorSemanticRetriever(factory, config)


def _plan(
    source_account_ids,
    *,
    semantic_k: int = 50,
    filters: ResolvedFilters | None = None,
    vector: list[float] | None = None,
    hints: PlanHints | None = None,
) -> SearchPlan:
    account_id = uuid.uuid4()
    values = tuple(vector if vector is not None else QUERY)
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(
            account_id=account_id, source_account_ids=frozenset(source_account_ids)
        ),
        filters=filters or ResolvedFilters(),
        resolved_entities=(),
        query=PreparedQuery(
            semantic_text="roof",
            vector=QueryVector(
                values=values, model=_MODEL, model_version=_VERSION, digest="d"
            ),
        ),
        strategy=SearchStrategy.RANKED,
        mode_requested=SearchMode.SEMANTIC,
        mode_effective=SearchMode.SEMANTIC,
        presentation=Presentation(
            sort=SortOrder.RELEVANCE,
            group_by=GroupBy.MESSAGE,
            view=ResultView.SNIPPET,
            limit=10,
        ),
        budgets=Budgets(
            lexical_k=50, semantic_k=semantic_k, fused_k=40, rerank_k=30, window_k=25
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=_MODEL,
            embedding_version=_VERSION,
            reranker=None,
        ),
        hints=hints or PlanHints(),
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
    emb=None,
    emb_sha="abc",
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
        emb_bge_m3_v1=emb,
        emb_bge_m3_v1_text_sha256=emb_sha if emb is not None else None,
    )
    db_session.add(chunk)
    return chunk


def _run(retriever, plan):
    return asyncio.run(retriever.retrieve(plan))


def _ids(result):
    return [hit.chunk_id for hit in result.hits]


def test_nearest_neighbor_ordering_and_rank(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    emails = [_email(migrated_db_session, source, f"m{i}@x") for i in range(3)]
    near = _chunk(migrated_db_session, source, emails[0], emb=_vec(1.0, 0))
    orth = _chunk(migrated_db_session, source, emails[1], emb=_vec(1.0, 1))
    far = _chunk(migrated_db_session, source, emails[2], emb=_vec(-1.0, 0))
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}))

    assert _ids(result) == [near.id, orth.id, far.id]
    assert [hit.rank for hit in result.hits] == [1, 2, 3]
    assert result.hits[0].distance < result.hits[1].distance < result.hits[2].distance


def test_email_id_is_populated(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    email = _email(migrated_db_session, source, "a@x")
    chunk = _chunk(migrated_db_session, source, email, emb=_vec(1.0, 0))
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}))

    assert result.hits[0].email_id == email.id
    assert result.hits[0].chunk_id == chunk.id


def test_deterministic_tie_break(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, emb=_vec(1.0, 0))
    c2 = _chunk(migrated_db_session, source, e2, emb=_vec(1.0, 0))
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=10))

    assert _ids(result) == sorted([c1.id, c2.id])


def test_top_k_is_respected(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    for i in range(5):
        email = _email(migrated_db_session, source, f"e{i}@x")
        _chunk(migrated_db_session, source, email, emb=_vec(1.0, i))
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=3))

    assert len(result.hits) == 3


def test_scope_always_applied(migrated_engine, migrated_db_session):
    in_source = _source(migrated_db_session, None, "in-scope")
    out_source = _source(migrated_db_session, None, "out-of-scope")
    in_email = _email(migrated_db_session, in_source, "in@x")
    out_email = _email(migrated_db_session, out_source, "out@x")
    in_chunk = _chunk(migrated_db_session, in_source, in_email, emb=_vec(1.0, 0))
    _chunk(migrated_db_session, out_source, out_email, emb=_vec(1.0, 0))
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({in_source.id}))

    assert _ids(result) == [in_chunk.id]


def test_null_embeddings_never_returned(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    embedded = _chunk(migrated_db_session, source, e1, emb=_vec(1.0, 0))
    null = _chunk(migrated_db_session, source, e2, emb=None)
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=10))

    assert _ids(result) == [embedded.id]
    assert null.id not in _ids(result)


def test_stale_embedding_excluded_then_included(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    fresh = _chunk(migrated_db_session, source, e1, emb=_vec(1.0, 0))
    stale = _chunk(
        migrated_db_session, source, e2, emb=_vec(1.0, 0), emb_sha="stale-hash"
    )
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=10))
    assert _ids(result) == [fresh.id]

    migrated_db_session.execute(
        text(
            "UPDATE search.chunk SET emb_bge_m3_v1_text_sha256 = 'abc' WHERE id = :id"
        ),
        {"id": stale.id},
    )
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=10))
    assert set(_ids(result)) == {fresh.id, stale.id}


def test_default_filter_path_is_ann_iterative(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    email = _email(migrated_db_session, source, "a@x")
    _chunk(migrated_db_session, source, email, emb=_vec(1.0, 0))
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}))

    assert result.filter_path == "ann_iterative"


def test_exact_path_when_hint_is_selective(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    email = _email(migrated_db_session, source, "a@x")
    _chunk(migrated_db_session, source, email, emb=_vec(1.0, 0))
    migrated_db_session.commit()

    retriever = _retriever(
        migrated_engine, SemanticRetrievalConfig(exact_threshold=100)
    )
    result = _run(
        retriever,
        _plan({source.id}, hints=PlanHints(estimated_matching_chunks=1)),
    )

    assert result.filter_path == "exact"
    assert result.complete is True


def test_exact_and_ann_agree(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    for i in range(6):
        email = _email(migrated_db_session, source, f"e{i}@x")
        _chunk(migrated_db_session, source, email, emb=_vec(1.0, i))
    migrated_db_session.commit()

    ann = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=10))
    exact = _run(
        _retriever(migrated_engine, SemanticRetrievalConfig(exact_threshold=100)),
        _plan({source.id}, semantic_k=10, hints=PlanHints(estimated_matching_chunks=6)),
    )

    assert _ids(ann) == _ids(exact)


def test_fewer_than_k_is_complete(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    for i in range(2):
        email = _email(migrated_db_session, source, f"e{i}@x")
        _chunk(migrated_db_session, source, email, emb=_vec(1.0, i))
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=10))

    assert len(result.hits) == 2
    assert result.complete is True
    assert result.scan_limit_hit is False


def test_exactly_k_is_never_complete(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    for i in range(4):
        email = _email(migrated_db_session, source, f"e{i}@x")
        _chunk(migrated_db_session, source, email, emb=_vec(1.0, i))
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=3))

    assert len(result.hits) == 3
    assert result.complete is False
    assert result.scan_limit_hit is False


def test_scan_limit_hit_when_ann_budget_exhausted(migrated_engine, migrated_db_session):
    # Drop the btree indexes that could answer the scope predicate, so the query
    # below is forced onto the HNSW index (with seqscan also disabled). Otherwise
    # the planner prefers an exact btree+sort plan on a small table and the
    # approximate-scan behavior we're testing never runs.
    with migrated_engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS search.chunk_scope_time_idx"))
        conn.execute(text("DROP INDEX IF EXISTS search.chunk_list_idx"))

    source = _source(migrated_db_session, None, "google-personal")
    for i in range(15):
        email = _email(migrated_db_session, source, f"sent{i}@x")
        _chunk(migrated_db_session, source, email, direction="sent", emb=_near(i))
    for i in range(4):
        email = _email(migrated_db_session, source, f"recv{i}@x")
        _chunk(
            migrated_db_session, source, email, direction="received", emb=_vec(1.0, 1)
        )
    migrated_db_session.commit()

    engine = _seqscan_off_engine(migrated_engine.url)
    retriever = _retriever(
        engine, SemanticRetrievalConfig(iterative_scan="off", ef_search=10)
    )
    result = _run(
        retriever,
        _plan(
            {source.id},
            semantic_k=3,
            filters=ResolvedFilters(direction=Direction.RECEIVED),
        ),
    )

    assert result.scan_limit_hit is True
    assert result.complete is False


def test_sender_and_direction_filters(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    e3 = _email(migrated_db_session, source, "e3@x")
    c1 = _chunk(migrated_db_session, source, e1, emb=_vec(1.0, 0), sender="a@x.com")
    _chunk(migrated_db_session, source, e2, emb=_vec(1.0, 0), sender="b@x.com")
    c3 = _chunk(migrated_db_session, source, e3, emb=_vec(1.0, 0), sender="a@x.com")
    migrated_db_session.commit()

    result = _run(
        _retriever(migrated_engine),
        _plan(
            {source.id},
            semantic_k=10,
            filters=ResolvedFilters(senders=frozenset({"a@x.com"})),
        ),
    )

    assert set(_ids(result)) == {c1.id, c3.id}


def test_trash_spam_excluded_by_default(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, emb=_vec(1.0, 0))
    _chunk(migrated_db_session, source, e2, emb=_vec(1.0, 0), is_trash_or_spam=True)
    migrated_db_session.commit()

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=10))

    assert _ids(result) == [c1.id]


def test_hnsw_index_is_used(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    email = _email(migrated_db_session, source, "a@x")
    _chunk(migrated_db_session, source, email, emb=_vec(1.0, 0))
    migrated_db_session.commit()

    q_str = "[" + ",".join(str(v) for v in QUERY) + "]"
    with migrated_engine.connect() as conn:
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        rows = conn.execute(
            text(
                "EXPLAIN (ANALYZE, BUFFERS) SELECT id FROM search.chunk "
                "WHERE emb_bge_m3_v1 IS NOT NULL "
                f"ORDER BY emb_bge_m3_v1 <=> '{q_str}'::halfvec LIMIT 3"
            )
        ).fetchall()
    plan_text = "\n".join(str(row[0]) for row in rows)

    assert "chunk_emb_bge_m3_v1_hnsw" in plan_text


def test_works_without_index(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    e1 = _email(migrated_db_session, source, "e1@x")
    e2 = _email(migrated_db_session, source, "e2@x")
    c1 = _chunk(migrated_db_session, source, e1, emb=_vec(1.0, 0))
    c2 = _chunk(migrated_db_session, source, e2, emb=_vec(1.0, 1))
    migrated_db_session.commit()

    with migrated_engine.begin() as conn:
        conn.execute(text("DROP INDEX search.chunk_emb_bge_m3_v1_hnsw"))

    result = _run(_retriever(migrated_engine), _plan({source.id}, semantic_k=10))

    assert _ids(result) == [c1.id, c2.id]


def test_set_local_does_not_leak(migrated_engine, migrated_db_session):
    source = _source(migrated_db_session, None, "google-personal")
    email = _email(migrated_db_session, source, "a@x")
    _chunk(migrated_db_session, source, email, emb=_vec(1.0, 0))
    migrated_db_session.commit()

    _run(_retriever(migrated_engine), _plan({source.id}))

    with migrated_engine.connect() as conn:
        mode = conn.execute(text("SHOW hnsw.iterative_scan")).scalar()
    assert mode == "off"


def test_dimension_mismatch_rejected(migrated_engine):
    plan = _plan({uuid.uuid4()}, vector=[1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        _run(_retriever(migrated_engine), plan)


def test_zero_vector_rejected(migrated_engine):
    plan = _plan({uuid.uuid4()}, vector=[0.0] * _DIM)
    with pytest.raises(ValueError):
        _run(_retriever(migrated_engine), plan)


def test_backend_failure_raises_typed_error():
    engine = create_engine(
        "postgresql+psycopg://rosalind:rosalind@127.0.0.1:1/rosalind",
        connect_args={"connect_timeout": 1},
    )
    retriever = PgVectorSemanticRetriever(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    with pytest.raises(SemanticRetrievalError):
        _run(retriever, _plan({uuid.uuid4()}))


def _seqscan_off_engine(url) -> Engine:
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _disable_seqscan(dbapi_conn, _record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("SET enable_seqscan = off")
        cursor.close()
        dbapi_conn.commit()

    return engine
