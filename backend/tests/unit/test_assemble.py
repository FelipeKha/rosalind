"""Unit tests for the assembly step (online search pipeline, step 5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from rosalind.application.search import (
    Budgets,
    Cursor,
    FusionConfig,
    GroupBy,
    IndexVersions,
    LexicalQuery,
    PlanWarning,
    PreparedQuery,
    Presentation,
    RequestContext,
    RerankedHit,
    RerankResult,
    RerankStats,
    ResolvedFilters,
    ResultView,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SortOrder,
    WarningCode,
)
from rosalind.application.search.assemble import (
    ListResult,
    SearchResultData,
    assemble_list,
    assemble_ranked,
    make_snippet,
)
from rosalind.application.search.cursor import HmacCursorCodec
from rosalind.domain.search import ChunkKind

ACCOUNT = uuid.uuid4()
SA = uuid.uuid4()

A1 = uuid.uuid4()
A2 = uuid.uuid4()
B1 = uuid.uuid4()
C1 = uuid.uuid4()
EMAIL_A = uuid.uuid4()
EMAIL_B = uuid.uuid4()
EMAIL_C = uuid.uuid4()
THREAD_T = uuid.uuid4()
THREAD_U = uuid.uuid4()

CODEC = HmacCursorCodec(b"test-key")

_WHEN = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _plan(
    *,
    strategy: SearchStrategy = SearchStrategy.RANKED,
    group_by: GroupBy = GroupBy.MESSAGE,
    view: ResultView = ResultView.SNIPPET,
    limit: int = 2,
    window_k: int = 4,
    cursor: Cursor | None = None,
    warnings: tuple[PlanWarning, ...] = (),
    reranker: str | None = None,
) -> SearchPlan:
    if strategy is SearchStrategy.LIST:
        query = PreparedQuery()
        sort = SortOrder.DATE_DESC
    else:
        query = PreparedQuery(lexical=LexicalQuery(terms=("roof",)))
        sort = SortOrder.RELEVANCE
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(account_id=ACCOUNT, source_account_ids=frozenset({SA})),
        filters=ResolvedFilters(),
        resolved_entities=(),
        query=query,
        strategy=strategy,
        mode_requested=SearchMode.LEXICAL,
        mode_effective=SearchMode.LEXICAL,
        presentation=Presentation(sort=sort, group_by=group_by, view=view, limit=limit),
        budgets=Budgets(
            lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=window_k
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=reranker,
        ),
        fusion=FusionConfig(),
        cursor=cursor,
        warnings=warnings,
    )


def _data(
    chunk_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    thread_id: uuid.UUID | None = None,
    kind: ChunkKind = ChunkKind.EMAIL_BODY,
    display_text: str | None = "hello world",
    attachment_name: str | None = None,
) -> SearchResultData:
    return SearchResultData(
        chunk_id=chunk_id,
        item_id=item_id,
        thread_id=thread_id,
        chunk_kind=kind,
        occurred_at=_WHEN,
        sender_handle="mike@turnerroofing.com",
        subject="Roof quote",
        display_text=display_text,
        attachment_name=attachment_name,
    )


def _hit(
    chunk_id: uuid.UUID,
    rank: int,
    *,
    rerank_score: float | None = None,
    fused_score: float = 0.1,
) -> RerankedHit:
    return RerankedHit(
        chunk_id=chunk_id,
        rerank_rank=rank,
        rerank_score=rerank_score,
        fused_rank=rank,
        fused_score=fused_score,
    )


def _stats() -> RerankStats:
    return RerankStats(
        candidates_in=0,
        scored=0,
        dropped_missing=0,
        truncated_passages=0,
        batches=0,
        fetch_ms=0.0,
        score_ms=0.0,
    )


def _rerank(hits: tuple[RerankedHit, ...], *, applied: bool) -> RerankResult:
    return RerankResult(
        ranked=hits,
        applied=applied,
        model=None,
        warnings=(),
        stats=_stats(),
        elapsed_ms=0.0,
    )


# --------------------------------------------------------------------------
# Snippets
# --------------------------------------------------------------------------


def test_make_snippet_normalizes_whitespace() -> None:
    assert make_snippet("  a   b\nc  ", 100) == "a b c"


def test_make_snippet_truncates_with_ellipsis() -> None:
    assert make_snippet("abcdefghij", 5) == "abcde…"


def test_make_snippet_returns_none_for_none() -> None:
    assert make_snippet(None, 100) is None


# --------------------------------------------------------------------------
# Metadata vs snippet view
# --------------------------------------------------------------------------


def test_metadata_view_ignores_display_text() -> None:
    plan = _plan(view=ResultView.METADATA)
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1),), applied=False),
        (_data(A1, EMAIL_A, display_text="should not appear"),),
        CODEC,
    )
    assert response.results[0].snippet is None


def test_snippet_view_generates_snippet() -> None:
    plan = _plan(view=ResultView.SNIPPET)
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1),), applied=False),
        (_data(A1, EMAIL_A, display_text="the revised quote"),),
        CODEC,
    )
    assert response.results[0].snippet == "the revised quote"


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------


def test_message_grouping_first_occurrence_wins() -> None:
    plan = _plan(group_by=GroupBy.MESSAGE)
    response = assemble_ranked(
        plan,
        _rerank(
            (_hit(A1, 1), _hit(A2, 2), _hit(B1, 3)),
            applied=False,
        ),
        (_data(A1, EMAIL_A), _data(A2, EMAIL_A), _data(B1, EMAIL_B)),
        CODEC,
    )
    ids = [r.item_id for r in response.results]
    assert ids == [EMAIL_A, EMAIL_B]
    assert response.results[0].chunk_id == A1  # representative = best chunk


def test_thread_grouping_collapses_by_thread() -> None:
    plan = _plan(group_by=GroupBy.THREAD)
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1), _hit(A2, 2), _hit(B1, 3)), applied=False),
        (
            _data(A1, EMAIL_A, thread_id=THREAD_T),
            _data(A2, EMAIL_A, thread_id=THREAD_T),
            _data(B1, EMAIL_B, thread_id=THREAD_U),
        ),
        CODEC,
    )
    assert [r.thread_id for r in response.results] == [THREAD_T, THREAD_U]
    assert response.results[0].item_id == EMAIL_A


def test_threadless_messages_are_their_own_groups() -> None:
    plan = _plan(group_by=GroupBy.THREAD)
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1), _hit(B1, 2)), applied=False),
        (_data(A1, EMAIL_A, thread_id=None), _data(B1, EMAIL_B, thread_id=None)),
        CODEC,
    )
    assert [r.item_id for r in response.results] == [EMAIL_A, EMAIL_B]


# --------------------------------------------------------------------------
# Scores
# --------------------------------------------------------------------------


def test_rerank_score_used_when_applied() -> None:
    plan = _plan(reranker="bge-reranker")
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1, rerank_score=0.9, fused_score=0.1),), applied=True),
        (_data(A1, EMAIL_A),),
        CODEC,
    )
    assert response.results[0].score == 0.9


def test_fused_score_used_when_rerank_skipped() -> None:
    plan = _plan()
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1, rerank_score=None, fused_score=0.4),), applied=False),
        (_data(A1, EMAIL_A),),
        CODEC,
    )
    assert response.results[0].score == 0.4


def test_list_score_is_none() -> None:
    plan = _plan(
        strategy=SearchStrategy.LIST,
        limit=2,
    )
    listed = ListResult(items=(_data(A1, EMAIL_A),), total=1)
    response = assemble_list(plan, listed, CODEC)
    assert response.results[0].score is None


# --------------------------------------------------------------------------
# matched_in
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,expected",
    [
        (ChunkKind.EMAIL_BODY, "body"),
        (ChunkKind.EMAIL_QUOTE, "body"),
        (ChunkKind.ATTACHMENT, "attachment"),
    ],
)
def test_matched_in_maps_from_chunk_kind(kind, expected) -> None:
    plan = _plan()
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1),), applied=False),
        (_data(A1, EMAIL_A, kind=kind, attachment_name="quote.pdf"),),
        CODEC,
    )
    assert response.results[0].matched_in == expected


# --------------------------------------------------------------------------
# Vanished chunks / determinism
# --------------------------------------------------------------------------


def test_missing_chunk_is_dropped() -> None:
    plan = _plan(limit=2)
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1), _hit(B1, 2)), applied=False),
        (_data(A1, EMAIL_A),),  # B1 vanished
        CODEC,
    )
    assert [r.chunk_id for r in response.results] == [A1]


def test_deterministic_order_preserved() -> None:
    plan = _plan(limit=3)
    response = assemble_ranked(
        plan,
        _rerank((_hit(C1, 1), _hit(A1, 2), _hit(B1, 3)), applied=False),
        (_data(C1, EMAIL_C), _data(A1, EMAIL_A), _data(B1, EMAIL_B)),
        CODEC,
    )
    assert [r.chunk_id for r in response.results] == [C1, A1, B1]


# --------------------------------------------------------------------------
# Ranked pagination
# --------------------------------------------------------------------------


def test_grouped_pagination_skips_nothing() -> None:
    plan = _plan(group_by=GroupBy.MESSAGE, limit=2, window_k=4)
    data = (
        _data(A1, EMAIL_A),
        _data(A2, EMAIL_A),
        _data(B1, EMAIL_B),
        _data(C1, EMAIL_C),
    )
    hits = _rerank((_hit(A1, 1), _hit(A2, 2), _hit(B1, 3), _hit(C1, 4)), applied=False)

    page1 = assemble_ranked(plan, hits, data, CODEC)
    assert [r.item_id for r in page1.results] == [EMAIL_A, EMAIL_B]
    assert page1.next_cursor is not None

    cursor = CODEC.decode(page1.next_cursor, account_id=ACCOUNT, index_version="v1")
    assert cursor.window_offset == 2

    page2 = assemble_ranked(
        _plan(group_by=GroupBy.MESSAGE, limit=2, window_k=4, cursor=cursor),
        hits,
        data,
        CODEC,
    )
    assert [r.item_id for r in page2.results] == [EMAIL_C]
    assert page2.next_cursor is None


def test_no_next_cursor_at_end_of_window() -> None:
    plan = _plan(limit=2, window_k=2)
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1), _hit(B1, 2)), applied=False),
        (_data(A1, EMAIL_A), _data(B1, EMAIL_B)),
        CODEC,
    )
    assert response.next_cursor is None


# --------------------------------------------------------------------------
# Warnings and applied filters
# --------------------------------------------------------------------------


def test_warnings_are_deduplicated() -> None:
    warning = PlanWarning(code=WarningCode.UNSEEN_HANDLE, message="nobody")
    plan = _plan(warnings=(warning, warning))
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1),), applied=False),
        (_data(A1, EMAIL_A),),
        CODEC,
    )
    assert response.warnings == (warning,)


def test_applied_filters_echo_plan() -> None:
    plan = _plan()
    response = assemble_ranked(
        plan,
        _rerank((_hit(A1, 1),), applied=False),
        (_data(A1, EMAIL_A),),
        CODEC,
    )
    assert response.applied_filters == plan.applied()


# --------------------------------------------------------------------------
# List pagination
# --------------------------------------------------------------------------


def test_list_keyset_next_cursor_advances() -> None:
    plan = _plan(strategy=SearchStrategy.LIST, limit=1)
    listed = ListResult(
        items=(
            _data(A1, EMAIL_A),
            _data(B1, EMAIL_B),
        ),
        total=2,
    )
    response = assemble_list(plan, listed, CODEC)
    assert len(response.results) == 1
    assert response.next_cursor is not None

    cursor = CODEC.decode(response.next_cursor, account_id=ACCOUNT, index_version="v1")
    assert cursor.list_position is not None
    assert cursor.list_position.email_id == EMAIL_A


def test_list_total_estimate_and_no_next_cursor() -> None:
    plan = _plan(strategy=SearchStrategy.LIST, limit=2)
    listed = ListResult(items=(_data(A1, EMAIL_A),), total=7)
    response = assemble_list(plan, listed, CODEC)
    assert response.total_estimate == 7
    assert response.next_cursor is None
