"""pgvector semantic retrieval adapter for online search step 2.2.

Runs filtered vector retrieval against ``search.chunk`` using the existing
``halfvec`` embedding column and (optionally) its HNSW index. It owns every
pgvector/PostgreSQL concept (``<=>``, ``halfvec_cosine_ops``, ``SET LOCAL
hnsw.*``), so ``application`` stays engine-agnostic.

Two paths are supported, mirroring the ``SemanticResult`` contract:

* ``exact`` — materialize the filtered rows, compute exact cosine distances,
  sort, take the top ``semantic_k``. Always ``complete``.
* ``ann_iterative`` — an HNSW approximate scan with iterative scans enabled, so
  filtered ANN keeps scanning until it finds ``semantic_k`` qualifying rows or
  hits ``hnsw.max_scan_tuples``. Completeness is decided by a bounded exact
  count, never by "we got fewer than k rows".

The semantic universe is a strict subset of the lexical one: the shared scope +
filters, plus a fresh, non-null embedding (``emb IS NOT NULL`` and the companion
text hash equal to ``text_sha256``, so a changed chunk's stale vector is never
returned).

Correctness notes (pgvector 0.8.6):

* ``hnsw.iterative_scan`` defaults to ``off``; it is set explicitly per query.
* ``hnsw.ef_search`` is valid in ``1..1000``; it is raised to at least
  ``semantic_k`` so a top-k query can actually return ``k`` candidates.
* The scope predicate is mandatory and always applied via ``source_account_num``,
  resolved from ``plan.scope``; returned rows are re-checked against it.
* Deterministic ordering (``distance ASC, id ASC``) makes results reproducible.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from pgvector.sqlalchemy.halfvec import HALFVEC
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import BindParameter, ColumnElement

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.embedding_spaces import (
    SpaceColumns,
    space_columns,
    space_for,
)
from rosalind.adapters.outbound.search.filters import filter_conditions, scope_nums
from rosalind.application.search import (
    QueryVector,
    SearchPlan,
    SemanticFilterPath,
    SemanticHit,
    SemanticResult,
    SemanticRetrievalError,
)
from rosalind.domain.search import EmbeddingSpace

__all__ = ["PgVectorSemanticRetriever", "SemanticRetrievalConfig", "query_bind"]

_DEFAULT_EF_SEARCH = 40
_MAX_EF_SEARCH = 1000
_ITERATIVE_SCAN_MODES = ("off", "strict_order", "relaxed_order")


@dataclass(frozen=True, slots=True)
class SemanticRetrievalConfig:
    """Tuning for the semantic adapter; configuration, never agent input.

    Defaults are placeholders until the benchmark in
    ``backend/scripts/bench_semantic_retrieval.py`` sets them.
    """

    exact_threshold: int | None = None  # None disables the auto-exact path
    iterative_scan: Literal["off", "strict_order", "relaxed_order"] = "strict_order"
    max_scan_tuples: int | None = None  # None = pgvector default (20000)
    scan_mem_multiplier: float | None = None  # None = pgvector default (1)
    ef_search: int | None = None  # None = default 40, raised to semantic_k
    statement_timeout_ms: int | None = None  # None = no statement timeout

    def __post_init__(self) -> None:
        if self.iterative_scan not in _ITERATIVE_SCAN_MODES:
            raise ValueError(f"iterative_scan must be one of {_ITERATIVE_SCAN_MODES}")
        if self.exact_threshold is not None and self.exact_threshold < 0:
            raise ValueError("exact_threshold cannot be negative")
        if self.ef_search is not None and not 1 <= self.ef_search <= _MAX_EF_SEARCH:
            raise ValueError(f"ef_search must be within 1..{_MAX_EF_SEARCH}")
        if self.max_scan_tuples is not None and self.max_scan_tuples < 1:
            raise ValueError("max_scan_tuples must be positive")
        if self.scan_mem_multiplier is not None and not (
            1 <= self.scan_mem_multiplier <= 1000
        ):
            raise ValueError("scan_mem_multiplier must be within 1..1000")
        if self.statement_timeout_ms is not None and self.statement_timeout_ms <= 0:
            raise ValueError("statement_timeout_ms must be positive")


def query_bind(space: EmbeddingSpace) -> BindParameter:
    """A ``halfvec``-typed bind for the query vector.

    Binding as ``HALFVEC`` (rather than a plain list, which psycopg would send
    as a text array) is what lets the planner use the ``halfvec_cosine_ops``
    operator and index.
    """
    return bindparam("q", type_=HALFVEC(space.dimension))


def classify_ann_completeness(
    hits_count: int, semantic_k: int, bounded_count: int
) -> tuple[bool, bool]:
    """Decide ``(complete, scan_limit_hit)`` for the ANN path.

    ``bounded_count`` is ``min(total_matching, semantic_k)``, so it is the number
    of matching chunks that *exist* unless it was clamped at ``semantic_k``.
    Exactly ``semantic_k`` hits is never ``complete`` (the ANN path can't know
    whether more matches exist).
    """
    if hits_count >= semantic_k:
        return False, False
    return bounded_count == hits_count, bounded_count > hits_count


class PgVectorSemanticRetriever:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        config: SemanticRetrievalConfig | None = None,
    ):
        self._factory = session_factory
        self._config = config or SemanticRetrievalConfig()

    async def retrieve(self, plan: SearchPlan) -> SemanticResult:
        return await asyncio.to_thread(self._retrieve, plan)

    def _retrieve(self, plan: SearchPlan) -> SemanticResult:
        vector = plan.query.vector
        if vector is None:
            raise ValueError("semantic retrieval requires a query vector")

        started = time.perf_counter()
        space = self._resolve_space(plan)
        self._validate_vector(vector, space)
        cols = space_columns(space.name)

        try:
            with self._factory() as session:
                nums = scope_nums(session, plan.scope.source_account_ids)
                filter_path = self._choose_path(session, plan, nums, cols)
                if filter_path == "exact":
                    rows = self._exact(session, plan, nums, cols, vector, space)
                    complete, scan_limit_hit = True, False
                else:
                    rows, complete, scan_limit_hit = self._ann(
                        session, plan, nums, cols, vector, space
                    )
                hits = self._to_hits(rows, nums)
        except SemanticRetrievalError:
            raise
        except SQLAlchemyError as exc:
            raise SemanticRetrievalError("semantic retrieval failed") from exc

        return SemanticResult(
            hits=hits,
            complete=complete,
            filter_path=filter_path,
            scan_limit_hit=scan_limit_hit,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    # -- validation -------------------------------------------------------

    def _resolve_space(self, plan: SearchPlan) -> EmbeddingSpace:
        model = plan.versions.embedding_model
        version = plan.versions.embedding_version
        if model is None or version is None:
            raise ValueError("semantic retrieval requires embedding model/version")
        return space_for(model, version)

    def _validate_vector(self, vector: QueryVector, space: EmbeddingSpace) -> None:
        if len(vector.values) != space.dimension:
            raise ValueError(
                f"query vector has {len(vector.values)} dims, expected {space.dimension}"
            )
        if not all(math.isfinite(value) for value in vector.values):
            raise ValueError("query vector must contain only finite values")
        if all(value == 0.0 for value in vector.values):
            raise ValueError(
                "query vector must be non-zero (cosine distance is undefined)"
            )

    # -- path selection ---------------------------------------------------

    def _choose_path(
        self,
        session: Session,
        plan: SearchPlan,
        nums: Sequence[int],
        cols: SpaceColumns,
    ) -> SemanticFilterPath:
        threshold = self._config.exact_threshold
        if threshold is None:
            return "ann_iterative"

        estimated = plan.hints.estimated_matching_chunks
        if estimated is not None:
            return "exact" if estimated <= threshold else "ann_iterative"

        count = self._bounded_count(session, plan, nums, cols, threshold + 1)
        return "exact" if count <= threshold else "ann_iterative"

    def _bounded_count(
        self,
        session: Session,
        plan: SearchPlan,
        nums: Sequence[int],
        cols: SpaceColumns,
        limit: int,
    ) -> int:
        chunk = models.Chunk
        subquery = (
            select(chunk.id)
            .where(*self._universe(plan, nums, cols))
            .limit(limit)
            .subquery()
        )
        return int(session.scalar(select(func.count()).select_from(subquery)) or 0)

    # -- retrieval paths --------------------------------------------------

    def _exact(
        self,
        session: Session,
        plan: SearchPlan,
        nums: Sequence[int],
        cols: SpaceColumns,
        vector: QueryVector,
        space: EmbeddingSpace,
    ) -> list[tuple[uuid.UUID, uuid.UUID, int, float]]:
        chunk = models.Chunk
        query = query_bind(space)

        # MATERIALIZED forces a real sort over the filtered rows, so the outer
        # distance ordering cannot turn back into an HNSW nearest-neighbor scan.
        filtered = (
            select(
                chunk.id,
                chunk.email_id,
                chunk.source_account_num,
                cols.vector.label("emb"),
            )
            .where(*self._universe(plan, nums, cols))
            .cte("filtered")
            .prefix_with("MATERIALIZED")
        )

        distance = filtered.c.emb.cosine_distance(query)
        stmt = (
            select(
                filtered.c.id,
                filtered.c.email_id,
                filtered.c.source_account_num,
                distance.label("distance"),
            )
            .order_by(distance.asc(), filtered.c.id.asc())
            .limit(plan.budgets.semantic_k)
        )
        return cast(
            "list[tuple[uuid.UUID, uuid.UUID, int, float]]",
            session.execute(stmt, {"q": list(vector.values)}).all(),
        )

    def _ann(
        self,
        session: Session,
        plan: SearchPlan,
        nums: Sequence[int],
        cols: SpaceColumns,
        vector: QueryVector,
        space: EmbeddingSpace,
    ) -> tuple[list[tuple[uuid.UUID, uuid.UUID, int, float]], bool, bool]:
        chunk = models.Chunk
        semantic_k = plan.budgets.semantic_k
        query = query_bind(space)
        distance = cols.vector.cosine_distance(query)

        self._apply_hnsw_settings(session, semantic_k)

        stmt = (
            select(
                chunk.id,
                chunk.email_id,
                chunk.source_account_num,
                distance.label("distance"),
            )
            .where(*self._universe(plan, nums, cols))
            .order_by(distance.asc(), chunk.id.asc())
            .limit(semantic_k)
        )
        rows = cast(
            "list[tuple[uuid.UUID, uuid.UUID, int, float]]",
            session.execute(stmt, {"q": list(vector.values)}).all(),
        )

        if len(rows) >= semantic_k:
            return rows, False, False

        bounded = self._bounded_count(session, plan, nums, cols, semantic_k)
        complete, scan_limit_hit = classify_ann_completeness(
            len(rows), semantic_k, bounded
        )
        return rows, complete, scan_limit_hit

    def _apply_hnsw_settings(self, session: Session, semantic_k: int) -> None:
        config = self._config
        effective_ef = max(config.ef_search or _DEFAULT_EF_SEARCH, semantic_k)
        # Load the pgvector library before setting its GUCs: until a backend has
        # used a vector function/type, the ``hnsw.*`` names are only reserved-prefix
        # placeholders, so a ``SET LOCAL`` on them would be accepted but silently
        # no-op. Touching a halfvec function makes them real for this transaction.
        session.execute(text("SELECT vector_dims('[1,0]'::halfvec)"))
        _set_local(session, "hnsw.iterative_scan", repr(config.iterative_scan))
        _set_local(session, "hnsw.ef_search", str(effective_ef))
        if config.max_scan_tuples is not None:
            _set_local(session, "hnsw.max_scan_tuples", str(config.max_scan_tuples))
        if config.scan_mem_multiplier is not None:
            _set_local(
                session, "hnsw.scan_mem_multiplier", str(config.scan_mem_multiplier)
            )
        if config.statement_timeout_ms is not None:
            _set_local(session, "statement_timeout", str(config.statement_timeout_ms))

    # -- shared predicates -------------------------------------------------

    def _universe(
        self, plan: SearchPlan, nums: Sequence[int], cols: SpaceColumns
    ) -> list[ColumnElement[bool]]:
        chunk = models.Chunk
        conditions: list[ColumnElement[bool]] = [chunk.source_account_num.in_(nums)]
        conditions.extend(filter_conditions(plan))
        conditions.append(cols.vector.is_not(None))
        conditions.append(cols.hash_ == chunk.text_sha256)
        return conditions

    def _to_hits(
        self,
        rows: Sequence[tuple[uuid.UUID, uuid.UUID, int, float]],
        nums: Sequence[int],
    ) -> tuple[SemanticHit, ...]:
        allowed = set(nums)
        hits: list[SemanticHit] = []
        for rank, (chunk_id, email_id, num, distance) in enumerate(rows, start=1):
            if num not in allowed:
                raise SemanticRetrievalError(
                    "retrieved chunk is outside the search scope"
                )
            hits.append(
                SemanticHit(
                    chunk_id=chunk_id,
                    email_id=email_id,
                    rank=rank,
                    distance=float(distance),
                )
            )
        return tuple(hits)


def _set_local(session: Session, setting: str, value: str) -> None:
    """Run a ``SET LOCAL`` for the current transaction.

    Values are validated literals (a config enum, or an int/float checked in
    ``SemanticRetrievalConfig.__post_init__``), so they are inlined rather than
    bound — PostgreSQL does not accept bind parameters in ``SET``.
    """
    session.execute(text(f"SET LOCAL {setting} = {value}"))
