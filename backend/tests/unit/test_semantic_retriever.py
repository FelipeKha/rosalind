"""Unit tests for the semantic retrieval adapter's pure pieces.

No database: the completeness classifier, config validation, the embedding-space
lookup, the ``halfvec`` query bind (operator + cast), and the path-selection
policy.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import cast

import pytest
from pgvector.sqlalchemy.halfvec import HALFVEC
from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.embedding_spaces import (
    embedding_space,
    space_columns,
    space_for,
)
from rosalind.adapters.outbound.search.semantic import (
    PgVectorSemanticRetriever,
    SemanticRetrievalConfig,
    classify_ann_completeness,
    query_bind,
)
from rosalind.application.search import (
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
    SortOrder,
)
from rosalind.application.search.plan import Budgets, PlanHints

_SPACE = embedding_space("bge_m3_v1")

# A retriever whose session is never opened: the path-policy tests below only
# exercise branches that do not touch the database.
_NOOP_SESSION = cast(Session, None)
_NOOP_FACTORY = cast(Callable[[], Session], lambda: _NOOP_SESSION)


def _retriever(config: SemanticRetrievalConfig) -> PgVectorSemanticRetriever:
    return PgVectorSemanticRetriever(_NOOP_FACTORY, config)


def _vector(dimension: int = 1024) -> QueryVector:
    values = tuple(1.0 / (dimension**0.5) for _ in range(dimension))
    return QueryVector(
        values=values,
        model="BAAI/bge-m3",
        model_version="bge_m3_v1",
        digest="abc",
    )


def _plan(*, hints: PlanHints | None = None) -> SearchPlan:
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
        query=PreparedQuery(semantic_text="roof", vector=_vector()),
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
            lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=25
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model="BAAI/bge-m3",
            embedding_version="bge_m3_v1",
            reranker=None,
        ),
        hints=hints or PlanHints(),
    )


def test_classify_ann_completeness_at_least_k_is_never_complete() -> None:
    assert classify_ann_completeness(50, 50, 50) == (False, False)
    assert classify_ann_completeness(5, 5, 5) == (False, False)


def test_classify_ann_completeness_underfilled_all_found() -> None:
    assert classify_ann_completeness(3, 50, 3) == (True, False)


def test_classify_ann_completeness_underfilled_scan_hit_limit() -> None:
    assert classify_ann_completeness(3, 50, 50) == (False, True)
    assert classify_ann_completeness(3, 50, 8) == (False, True)


def test_config_rejects_bad_iterative_scan() -> None:
    with pytest.raises(ValueError):
        SemanticRetrievalConfig(iterative_scan="banana")  # type: ignore[arg-type]


def test_config_rejects_bad_ef_search() -> None:
    with pytest.raises(ValueError):
        SemanticRetrievalConfig(ef_search=0)
    with pytest.raises(ValueError):
        SemanticRetrievalConfig(ef_search=1001)


def test_config_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError):
        SemanticRetrievalConfig(exact_threshold=-1)


def test_config_rejects_bad_scan_tuples_and_mem_multiplier() -> None:
    with pytest.raises(ValueError):
        SemanticRetrievalConfig(max_scan_tuples=0)
    with pytest.raises(ValueError):
        SemanticRetrievalConfig(scan_mem_multiplier=0.5)


def test_config_defaults_are_valid() -> None:
    config = SemanticRetrievalConfig()
    assert config.iterative_scan == "strict_order"
    assert config.exact_threshold is None


def test_space_for_resolves_by_model_and_version() -> None:
    assert space_for("BAAI/bge-m3", "bge_m3_v1").name == "bge_m3_v1"


def test_space_for_unknown_model_raises() -> None:
    with pytest.raises(KeyError):
        space_for("unknown/model", "v1")


def test_query_bind_is_halfvec_with_expected_dimension() -> None:
    bind = query_bind(_SPACE)
    assert isinstance(bind.type, HALFVEC)
    assert bind.type.dim == 1024


def test_query_uses_cosine_distance_operator() -> None:
    distance = space_columns(_SPACE.name).vector.cosine_distance(query_bind(_SPACE))
    compiled = str(select(models.Chunk.id, distance.label("distance")).compile())
    assert "<=>" in compiled


def test_path_policy_disabled_threshold_always_ann() -> None:
    retriever = _retriever(SemanticRetrievalConfig())
    assert (
        retriever._choose_path(_NOOP_SESSION, _plan(), [], space_columns("bge_m3_v1"))
        == "ann_iterative"
    )


def test_path_policy_uses_hint() -> None:
    retriever = _retriever(SemanticRetrievalConfig(exact_threshold=100))
    assert (
        retriever._choose_path(
            _NOOP_SESSION,
            _plan(hints=PlanHints(estimated_matching_chunks=50)),
            [],
            space_columns("bge_m3_v1"),
        )
        == "exact"
    )
    assert (
        retriever._choose_path(
            _NOOP_SESSION,
            _plan(hints=PlanHints(estimated_matching_chunks=150)),
            [],
            space_columns("bge_m3_v1"),
        )
        == "ann_iterative"
    )
