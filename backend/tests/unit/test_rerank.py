"""Unit tests for step 4 rerank orchestration.

Pure and database-free: fake ``ChunkTextPort`` / ``RerankerPort`` / tokenizer
exercise window selection, deterministic ordering, the passage-token budget,
truncation, and the all-or-nothing fallback to fused order.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import fields

import pytest

from rosalind.application.search import (
    ChunkText,
    FusedCandidate,
    FusedCandidates,
    GroupBy,
    IndexVersions,
    LexicalQuery,
    PreparedQuery,
    Presentation,
    RequestContext,
    RerankBackendError,
    RerankedHit,
    RerankError,
    ResolvedFilters,
    ResultView,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SortOrder,
    rerank,
)
from rosalind.application.search.plan import Budgets, WarningCode
from rosalind.application.search.ports import RerankConfig, RerankTextMode


class _WordCounter:
    """Token counter where one whitespace-separated word equals one token."""

    version = "test"

    def count(self, text: str) -> int:
        return len(text.split())

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        words = text.split()
        if not words:
            return [0]
        if len(words) <= max_tokens:
            return [0, len(text)]
        pos = 0
        for index in range(max_tokens):
            pos = text.index(words[index], pos) + len(words[index])
        return [0, pos, len(text)]


class _FakeTexts:
    def __init__(self, mapping: dict[uuid.UUID, str]) -> None:
        self._mapping = mapping
        self.mode: RerankTextMode | None = None

    async def get_rerank_texts(
        self, chunk_ids: tuple[uuid.UUID, ...], mode: RerankTextMode
    ) -> tuple[ChunkText, ...]:
        self.mode = mode
        return tuple(
            ChunkText(chunk_id=chunk_id, text=self._mapping[chunk_id])
            for chunk_id in chunk_ids
            if chunk_id in self._mapping
        )


class _FakeReranker:
    def __init__(
        self,
        *,
        scores: tuple[float, ...] | None = None,
        error: Exception | None = None,
        sleep_s: float | None = None,
    ) -> None:
        self._scores = scores
        self._error = error
        self._sleep_s = sleep_s
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def rerank(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        self.calls.append((query, passages))
        if self._sleep_s is not None:
            await asyncio.sleep(self._sleep_s)
        if self._error is not None:
            raise self._error
        if self._scores is not None:
            return self._scores
        return tuple(float(len(passages) - index) for index in range(len(passages)))


def _plan(
    *,
    reranker: str | None = "bge-reranker-v2-m3/v1",
    terms: tuple[str, ...] = ("roof", "quote"),
    rerank_k: int = 30,
    window_k: int = 25,
    fused_k: int = 40,
    limit: int = 10,
) -> SearchPlan:
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
        query=PreparedQuery(lexical=LexicalQuery(terms=terms)),
        strategy=SearchStrategy.RANKED,
        mode_requested=SearchMode.LEXICAL,
        mode_effective=SearchMode.LEXICAL,
        presentation=Presentation(
            sort=SortOrder.RELEVANCE,
            group_by=GroupBy.MESSAGE,
            view=ResultView.SNIPPET,
            limit=limit,
        ),
        budgets=Budgets(
            lexical_k=50,
            semantic_k=50,
            fused_k=fused_k,
            rerank_k=rerank_k,
            window_k=window_k,
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=reranker,
        ),
    )


def _candidate(chunk_id: uuid.UUID, rank: int) -> FusedCandidate:
    return FusedCandidate(
        chunk_id=chunk_id,
        email_id=uuid.uuid4(),
        fused_score=1.0 / (60 + rank),
        fused_rank=rank,
        lexical_rank=rank,
        lexical_score=10.0,
        semantic_rank=None,
        semantic_distance=None,
    )


def _fused(*chunk_ids: uuid.UUID) -> FusedCandidates:
    return FusedCandidates(
        candidates=tuple(
            _candidate(chunk_id, rank) for rank, chunk_id in enumerate(chunk_ids, 1)
        ),
        lexical_used=True,
        semantic_used=False,
        dropped_by_item_cap=0,
    )


def _run(
    plan: SearchPlan,
    fused: FusedCandidates,
    *,
    texts: _FakeTexts,
    reranker: _FakeReranker,
    config: RerankConfig | None = None,
    counter: _WordCounter | None = None,
):
    return asyncio.run(
        rerank(
            plan,
            fused,
            texts=texts,
            reranker=reranker,
            token_counter=counter or _WordCounter(),
            config=config or RerankConfig(max_input_tokens=100),
        )
    )


def _ids(result):
    return [hit.chunk_id for hit in result.ranked]


def test_disabled_returns_fused_order_without_warning() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    fused = _fused(a, b)
    plan = _plan(reranker=None)

    result = _run(plan, fused, texts=_FakeTexts({}), reranker=_FakeReranker())

    assert result.applied is False
    assert result.model is None
    assert result.warnings == ()
    assert _ids(result) == [a, b]
    assert all(hit.rerank_score is None for hit in result.ranked)
    assert [hit.rerank_rank for hit in result.ranked] == [1, 2]


def test_disabled_limits_to_window_k() -> None:
    chunks = [uuid.uuid4() for _ in range(5)]
    plan = _plan(reranker=None, fused_k=5, rerank_k=5, window_k=3, limit=3)

    result = _run(plan, _fused(*chunks), texts=_FakeTexts({}), reranker=_FakeReranker())

    assert len(result.ranked) == 3
    assert _ids(result) == chunks[:3]


def test_empty_candidates_returns_not_applied() -> None:
    result = _run(_plan(), _fused(), texts=_FakeTexts({}), reranker=_FakeReranker())

    assert result.applied is False
    assert result.ranked == ()
    assert result.stats.candidates_in == 0


def test_top_rerank_k_selected() -> None:
    chunks = [uuid.uuid4() for _ in range(5)]
    texts = _FakeTexts({chunk: f"text {chunk}" for chunk in chunks})
    reranker = _FakeReranker()

    result = _run(
        _plan(rerank_k=3, window_k=3, limit=3),
        _fused(*chunks),
        texts=texts,
        reranker=reranker,
    )

    assert result.stats.candidates_in == 3
    assert len(reranker.calls[0][1]) == 3
    assert _ids(result) == chunks[:3]


def test_scores_mapped_to_correct_chunk_ids() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    texts = _FakeTexts({a: "aa", b: "bb", c: "cc"})
    # b scores highest, then a, then c.
    reranker = _FakeReranker(scores=(2.0, 3.0, 1.0))

    result = _run(_plan(), _fused(a, b, c), texts=texts, reranker=reranker)

    assert _ids(result) == [b, a, c]
    assert [hit.rerank_score for hit in result.ranked] == [3.0, 2.0, 1.0]
    assert [hit.rerank_rank for hit in result.ranked] == [1, 2, 3]


def test_equal_score_uses_fused_rank_then_chunk_id() -> None:
    low = uuid.UUID("00000000-0000-0000-0000-000000000001")
    high = uuid.UUID("00000000-0000-0000-0000-000000000002")
    texts = _FakeTexts({low: "l", high: "h"})
    reranker = _FakeReranker(scores=(1.0, 1.0))

    result = _run(_plan(), _fused(low, high), texts=texts, reranker=reranker)

    assert _ids(result) == [low, high]


def test_single_candidate() -> None:
    a = uuid.uuid4()
    reranker = _FakeReranker(scores=(0.5,))

    result = _run(_plan(), _fused(a), texts=_FakeTexts({a: "aa"}), reranker=reranker)

    assert result.applied is True
    assert _ids(result) == [a]
    assert result.ranked[0].rerank_score == 0.5


def test_backend_failure_falls_back_to_fused_order() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    texts = _FakeTexts({a: "aa", b: "bb"})
    reranker = _FakeReranker(error=RerankBackendError("down"))

    result = _run(_plan(), _fused(a, b), texts=texts, reranker=reranker)

    assert result.applied is False
    assert _ids(result) == [a, b]
    assert all(hit.rerank_score is None for hit in result.ranked)
    assert [warning.code for warning in result.warnings] == [WarningCode.RERANK_SKIPPED]


def test_deadline_falls_back_without_partial_scores() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    texts = _FakeTexts({a: "aa", b: "bb"})
    reranker = _FakeReranker(sleep_s=0.05)
    config = RerankConfig(max_input_tokens=100, deadline_ms=1)

    result = _run(_plan(), _fused(a, b), texts=texts, reranker=reranker, config=config)

    assert result.applied is False
    assert _ids(result) == [a, b]
    assert all(hit.rerank_score is None for hit in result.ranked)


def test_score_count_mismatch_raises() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    texts = _FakeTexts({a: "aa", b: "bb"})
    reranker = _FakeReranker(scores=(1.0,))

    with pytest.raises(RerankError, match="returned 1 scores, expected 2"):
        _run(_plan(), _fused(a, b), texts=texts, reranker=reranker)


def test_missing_chunk_is_dropped_and_counted() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    # b is missing from the store (a rebuild shrank the chunk count).
    texts = _FakeTexts({a: "aa"})
    reranker = _FakeReranker(scores=(1.0,))

    result = _run(_plan(), _fused(a, b), texts=texts, reranker=reranker)

    assert result.applied is True
    assert _ids(result) == [a]
    assert result.stats.candidates_in == 2
    assert result.stats.scored == 1
    assert result.stats.dropped_missing == 1


def test_passage_budget_subtracts_query_tokens() -> None:
    a = uuid.uuid4()
    passage = " ".join(f"w{index}" for index in range(20))
    texts = _FakeTexts({a: passage})
    reranker = _FakeReranker(scores=(1.0,))
    # max_input_tokens=20, query "a b c d e" = 5 tokens, special = 3 → budget 12.
    plan = _plan(terms=("a", "b", "c", "d", "e"))
    config = RerankConfig(max_input_tokens=20)

    result = _run(plan, _fused(a), texts=texts, reranker=reranker, config=config)

    sent = reranker.calls[0][1][0]
    assert len(sent.split()) == 12
    assert result.stats.truncated_passages == 1
    assert result.warnings == ()


def test_query_is_never_truncated() -> None:
    a = uuid.uuid4()
    query_terms = tuple(f"q{index}" for index in range(10))
    texts = _FakeTexts({a: "short passage"})
    reranker = _FakeReranker(scores=(1.0,))
    plan = _plan(terms=query_terms)
    config = RerankConfig(max_input_tokens=50)

    _run(plan, _fused(a), texts=texts, reranker=reranker, config=config)

    assert reranker.calls[0][0] == " ".join(query_terms)


def test_query_with_no_passage_budget_raises() -> None:
    a = uuid.uuid4()
    texts = _FakeTexts({a: "aa"})
    reranker = _FakeReranker()
    # query "x y z" = 3 tokens, special = 3 → budget 0 for max_input_tokens=6.
    plan = _plan(terms=("x", "y", "z"))
    config = RerankConfig(max_input_tokens=6)

    with pytest.raises(RerankError, match="no passage budget"):
        _run(plan, _fused(a), texts=texts, reranker=reranker, config=config)


def test_text_mode_is_passed_to_the_port() -> None:
    a = uuid.uuid4()
    texts = _FakeTexts({a: "aa"})
    config = RerankConfig(max_input_tokens=100, text_mode=RerankTextMode.DISPLAY)

    _run(_plan(), _fused(a), texts=texts, reranker=_FakeReranker(), config=config)

    assert texts.mode is RerankTextMode.DISPLAY


def test_not_applied_and_applied_have_the_same_shape() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    texts = _FakeTexts({a: "aa", b: "bb"})
    skipped = _run(
        _plan(),
        _fused(a, b),
        texts=texts,
        reranker=_FakeReranker(error=RerankBackendError("down")),
    )
    applied = _run(
        _plan(), _fused(a, b), texts=texts, reranker=_FakeReranker(scores=(2.0, 1.0))
    )

    assert [f.name for f in fields(RerankedHit)] == [
        "chunk_id",
        "rerank_rank",
        "rerank_score",
        "fused_rank",
    ]
    assert skipped.applied is False
    assert applied.applied is True
    assert len(skipped.ranked) == len(applied.ranked) == 2
