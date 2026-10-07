"""Unit tests for step 3 fusion (reciprocal rank fusion).

Pure and database-free: the RRF arithmetic, weighted RRF, single-branch identity,
the per-message cap, truncation, deterministic ordering, metadata preservation,
and the branch/rank/UUID tie-break order.
"""

from __future__ import annotations

import uuid
from collections import Counter

import pytest

from rosalind.application.search import (
    FusedCandidates,
    FusionConfig,
    FusionStrategy,
    GroupBy,
    IndexVersions,
    LexicalHit,
    LexicalQuery,
    LexicalResult,
    PreparedQuery,
    Presentation,
    RequestContext,
    ResolvedFilters,
    ResultView,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SemanticHit,
    SemanticResult,
    SortOrder,
    fuse,
)
from rosalind.application.search.fusion import _Scored, _sort_key
from rosalind.application.search.plan import Budgets


def _plan(*, fused_k: int = 5, fusion: FusionConfig | None = None) -> SearchPlan:
    account_id = uuid.uuid4()
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(
            account_id=account_id, source_account_ids=frozenset({uuid.uuid4()})
        ),
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
            limit=fused_k,
        ),
        budgets=Budgets(
            lexical_k=50,
            semantic_k=50,
            fused_k=fused_k,
            rerank_k=1,
            window_k=fused_k,
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=None,
        ),
        fusion=fusion or FusionConfig(),
    )


def _lex(chunk_id, email_id, rank, score=10.0) -> LexicalHit:
    return LexicalHit(chunk_id=chunk_id, email_id=email_id, rank=rank, score=score)


def _sem(chunk_id, email_id, rank, distance=0.1) -> SemanticHit:
    return SemanticHit(
        chunk_id=chunk_id, email_id=email_id, rank=rank, distance=distance
    )


def _lex_result(*hits: LexicalHit) -> LexicalResult:
    return LexicalResult(hits=hits, exhausted=True, filter_path="pushdown")


def _sem_result(*hits: SemanticHit) -> SemanticResult:
    return SemanticResult(
        hits=hits, complete=True, filter_path="exact", scan_limit_hit=False
    )


def _chunk_ids(result: FusedCandidates) -> list[uuid.UUID]:
    return [candidate.chunk_id for candidate in result.candidates]


def test_rrf_arithmetic_with_k60() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ea, eb, ec = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lexical = _lex_result(_lex(a, ea, 1), _lex(b, eb, 2))
    semantic = _sem_result(_sem(a, ea, 3), _sem(c, ec, 1))

    result = fuse(_plan(), lexical, semantic)

    assert _chunk_ids(result) == [a, c, b]
    by_id = {candidate.chunk_id: candidate for candidate in result.candidates}
    assert by_id[a].fused_score == pytest.approx(1 / 61 + 1 / 63)
    assert by_id[b].fused_score == pytest.approx(1 / 62)
    assert by_id[c].fused_score == pytest.approx(1 / 61)


def test_weighted_rrf() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ea, eb, ec = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fusion = FusionConfig(lexical_weight=2.0, semantic_weight=1.0)
    lexical = _lex_result(_lex(a, ea, 1), _lex(b, eb, 2))
    semantic = _sem_result(_sem(a, ea, 1), _sem(c, ec, 1))

    result = fuse(_plan(fusion=fusion), lexical, semantic)

    assert _chunk_ids(result) == [a, b, c]
    by_id = {candidate.chunk_id: candidate for candidate in result.candidates}
    assert by_id[a].fused_score == pytest.approx(2 / 61 + 1 / 61)
    assert by_id[b].fused_score == pytest.approx(2 / 62)
    assert by_id[c].fused_score == pytest.approx(1 / 61)


def test_lexical_only_passes_through_unchanged() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ea, eb, ec = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lexical = _lex_result(_lex(a, ea, 1), _lex(b, eb, 2), _lex(c, ec, 3))

    result = fuse(_plan(), lexical, None)

    assert _chunk_ids(result) == [a, b, c]
    assert result.lexical_used is True
    assert result.semantic_used is False
    assert result.dropped_by_item_cap == 0
    assert [candidate.fused_rank for candidate in result.candidates] == [1, 2, 3]
    assert result.candidates[0].semantic_rank is None
    assert result.candidates[0].semantic_distance is None


def test_semantic_only_passes_through_unchanged() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ea, eb, ec = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    semantic = _sem_result(_sem(a, ea, 1), _sem(b, eb, 2), _sem(c, ec, 3))

    result = fuse(_plan(), None, semantic)

    assert _chunk_ids(result) == [a, b, c]
    assert result.lexical_used is False
    assert result.semantic_used is True
    assert result.candidates[0].lexical_rank is None
    assert result.candidates[0].lexical_score is None


def test_both_branches_none_raises() -> None:
    with pytest.raises(ValueError):
        fuse(_plan(), None, None)


def test_convex_strategy_is_not_implemented() -> None:
    fusion = FusionConfig(strategy=FusionStrategy.CONVEX, convex_alpha=0.5)
    with pytest.raises(NotImplementedError):
        fuse(_plan(fusion=fusion), _lex_result(), None)


def test_per_message_cap_drops_extras() -> None:
    a1, a2, a3, a4 = (uuid.uuid4() for _ in range(4))
    b1, b2 = uuid.uuid4(), uuid.uuid4()
    c1 = uuid.uuid4()
    email_a, email_b, email_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lexical = _lex_result(
        _lex(a1, email_a, 1),
        _lex(a2, email_a, 2),
        _lex(a3, email_a, 3),
        _lex(a4, email_a, 4),
        _lex(b1, email_b, 5),
        _lex(b2, email_b, 6),
        _lex(c1, email_c, 7),
    )

    result = fuse(
        _plan(fused_k=5, fusion=FusionConfig(max_chunks_per_item=2)), lexical, None
    )

    assert _chunk_ids(result) == [a1, a2, b1, b2, c1]
    assert result.dropped_by_item_cap == 2


def test_cap_does_not_interfere_under_limit() -> None:
    a1, a2 = uuid.uuid4(), uuid.uuid4()
    b1 = uuid.uuid4()
    email_a, email_b = uuid.uuid4(), uuid.uuid4()
    lexical = _lex_result(
        _lex(a1, email_a, 1), _lex(b1, email_b, 2), _lex(a2, email_a, 3)
    )

    result = fuse(
        _plan(fused_k=5, fusion=FusionConfig(max_chunks_per_item=2)), lexical, None
    )

    assert _chunk_ids(result) == [a1, b1, a2]
    assert result.dropped_by_item_cap == 0


def test_truncation_to_fused_k() -> None:
    chunks = [uuid.uuid4() for _ in range(5)]
    emails = [uuid.uuid4() for _ in range(5)]
    lexical = _lex_result(
        *(
            _lex(chunk, email, i + 1)
            for i, (chunk, email) in enumerate(zip(chunks, emails))
        )
    )

    result = fuse(_plan(fused_k=3), lexical, None)

    assert _chunk_ids(result) == chunks[:3]
    assert [candidate.fused_rank for candidate in result.candidates] == [1, 2, 3]


def test_branch_metadata_is_preserved() -> None:
    a = uuid.uuid4()
    ea = uuid.uuid4()
    lexical = _lex_result(_lex(a, ea, 2, score=7.5))
    semantic = _sem_result(_sem(a, ea, 5, distance=0.42))

    result = fuse(_plan(), lexical, semantic)

    hit = result.candidates[0]
    assert hit.lexical_rank == 2
    assert hit.lexical_score == 7.5
    assert hit.semantic_rank == 5
    assert hit.semantic_distance == 0.42


def test_inconsistent_email_id_across_branches_raises() -> None:
    a = uuid.uuid4()
    lexical = _lex_result(_lex(a, uuid.uuid4(), 1))
    semantic = _sem_result(_sem(a, uuid.uuid4(), 1))

    with pytest.raises(ValueError):
        fuse(_plan(), lexical, semantic)


def test_output_is_deterministic() -> None:
    emails = [uuid.uuid4() for _ in range(3)]
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    lexical = _lex_result(_lex(a, emails[0], 1), _lex(b, emails[0], 2))
    semantic = _sem_result(
        _sem(b, emails[0], 1), _sem(c, emails[1], 2), _sem(d, emails[2], 3)
    )

    first = fuse(_plan(), lexical, semantic)
    second = fuse(_plan(), lexical, semantic)

    assert first == second


def test_output_invariants_hold() -> None:
    emails = [uuid.uuid4() for _ in range(3)]
    c0a, c0b, c0c, c1a, c2a, c2b = (uuid.uuid4() for _ in range(6))
    lexical = _lex_result(
        _lex(c0a, emails[0], 1),
        _lex(c0b, emails[0], 2),
        _lex(c0c, emails[0], 3),
        _lex(c1a, emails[1], 4),
        _lex(c2a, emails[2], 5),
        _lex(c2b, emails[2], 6),
    )
    semantic = _sem_result(
        _sem(c0b, emails[0], 1), _sem(c2a, emails[2], 2), _sem(c1a, emails[1], 3)
    )

    result = fuse(
        _plan(fused_k=5, fusion=FusionConfig(max_chunks_per_item=2)), lexical, semantic
    )

    ids = _chunk_ids(result)
    assert len(ids) == len(set(ids))
    assert len(ids) <= 5
    counts = Counter(candidate.email_id for candidate in result.candidates)
    assert max(counts.values()) <= 2
    all_input = {hit.chunk_id for hit in lexical.hits} | {
        hit.chunk_id for hit in semantic.hits
    }
    assert set(ids) <= all_input
    assert [candidate.fused_rank for candidate in result.candidates] == list(
        range(1, len(ids) + 1)
    )


def _scored(chunk_id, fused_score, *, lexical_rank=None, semantic_rank=None) -> _Scored:
    return _Scored(
        chunk_id=chunk_id,
        email_id=uuid.uuid4(),
        fused_score=fused_score,
        lexical_rank=lexical_rank,
        lexical_score=None,
        semantic_rank=semantic_rank,
        semantic_distance=None,
    )


def test_sort_key_breaks_ties_by_branch_count_then_best_rank_then_id() -> None:
    low = uuid.UUID("00000000-0000-0000-0000-000000000001")
    high = uuid.UUID("00000000-0000-0000-0000-000000000002")

    # Same score: a candidate in both branches beats one in a single branch.
    single = _scored(low, 0.5, lexical_rank=1)
    double = _scored(high, 0.5, lexical_rank=1, semantic_rank=2)
    assert _sort_key(double) < _sort_key(single)

    # Same score and branch count: the lower best rank wins.
    low_best = _scored(low, 0.5, lexical_rank=1, semantic_rank=5)
    high_best = _scored(high, 0.5, lexical_rank=3, semantic_rank=2)
    assert _sort_key(low_best) < _sort_key(high_best)

    # Identical score, branch count, and best rank: the lower chunk id wins.
    first = _scored(low, 0.5, lexical_rank=1, semantic_rank=2)
    second = _scored(high, 0.5, lexical_rank=2, semantic_rank=1)
    assert _sort_key(first) < _sort_key(second)
