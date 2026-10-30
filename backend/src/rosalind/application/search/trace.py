"""Search trace: the intermediate state one online-search run produced.

Layer: ``application``. Plain frozen dataclasses with no Pydantic, SQLAlchemy,
or provider imports. The orchestrator (``SearchPipeline``) returns a
``SearchTrace`` so evaluation and auditing share the same run instead of
reimplementing the pipeline.

Two projections exist:

* The in-memory ``SearchTrace`` carries the plan, every stage result, the final
  ``SearchResponse``, and per-stage timings. The stage result types
  (``LexicalResult``, ``SemanticResult``, ``FusedCandidates``, ``RerankResult``)
  hold only chunk IDs, ranks, scores, flags and timings — never query text or
  chunk text — so a trace is content-free by construction.
* ``TraceSummary`` is the small, serializable projection used for logging and
  persistence. ``trace_level="minimal"`` (the production default) keeps counts,
  flags, versions, timings and the returned IDs; ``"full"`` additionally keeps
  the per-stage candidate ID lists. Full traces are never persisted by default.

The summary deliberately excludes filter *values* (they contain email
addresses); only filter names and list sizes are kept.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from rosalind.application.search.fusion import FusedCandidates
from rosalind.application.search.plan import ResolvedFilters, SearchPlan, WarningCode
from rosalind.application.search.rerank import RerankResult
from rosalind.application.search.result import SearchResponse
from rosalind.application.search.retrieve import LexicalResult
from rosalind.application.search.semantic import SemanticResult

__all__ = ["SearchTrace", "TraceLevel", "TraceSummary"]

TraceLevel = Literal["minimal", "full"]

_DEGRADED_CODES = frozenset(
    {
        WarningCode.MODE_DEGRADED,
        WarningCode.RETRIEVAL_DEGRADED,
        WarningCode.RERANK_SKIPPED,
    }
)


@dataclass(frozen=True, slots=True)
class SearchTrace:
    """Everything one run of the online search pipeline produced."""

    plan: SearchPlan
    response: SearchResponse
    lexical: LexicalResult | None = None
    semantic: SemanticResult | None = None
    fused: FusedCandidates | None = None
    reranked: RerankResult | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    trace_level: TraceLevel = "minimal"

    def to_summary(
        self,
        *,
        full: bool | None = None,
        include_plan: bool = False,
    ) -> TraceSummary:
        """Project the trace for logging/persistence.

        ``full=None`` follows the trace's own ``trace_level``. ``include_plan``
        is the opt-in replay capture (it embeds query text via the plan); off by
        default and never used in production.
        """
        keep_candidates = (self.trace_level == "full") if full is None else full
        return _summarize(
            self, keep_candidates=keep_candidates, include_plan=include_plan
        )


@dataclass(frozen=True, slots=True)
class TraceSummary:
    """Content-free, serializable summary of one search request."""

    request_id: uuid.UUID
    audit_id: uuid.UUID
    account_id: uuid.UUID
    client_id: str
    plan_fingerprint: str
    mode_requested: str
    mode_effective: str
    strategy: str
    index_version: str
    embedding_model: str | None
    embedding_version: str | None
    reranker_version: str | None
    filter_names: tuple[str, ...]
    filter_sizes: dict[str, int]
    lexical_count: int | None
    lexical_exhausted: bool | None
    lexical_filter_path: str | None
    lexical_elapsed_ms: float | None
    semantic_count: int | None
    semantic_complete: bool | None
    semantic_filter_path: str | None
    semantic_scan_limit_hit: bool | None
    semantic_elapsed_ms: float | None
    fused_count: int | None
    lexical_used: bool | None
    semantic_used: bool | None
    dropped_by_item_cap: int | None
    rerank_applied: bool | None
    rerank_model: str | None
    rerank_candidates_in: int | None
    rerank_scored: int | None
    rerank_dropped_missing: int | None
    rerank_truncated_passages: int | None
    rerank_elapsed_ms: float | None
    result_count: int
    warnings: tuple[str, ...]
    degraded: bool
    timings_ms: dict[str, float]
    returned_chunk_ids: tuple[uuid.UUID, ...]
    returned_item_ids: tuple[uuid.UUID, ...]
    lexical_candidate_ids: tuple[uuid.UUID, ...] | None = None
    semantic_candidate_ids: tuple[uuid.UUID, ...] | None = None
    fused_candidate_ids: tuple[uuid.UUID, ...] | None = None
    reranked_candidate_ids: tuple[uuid.UUID, ...] | None = None
    plan: SearchPlan | None = None


# --------------------------------------------------------------------------
# Projection helpers
# --------------------------------------------------------------------------


def _summarize(
    trace: SearchTrace,
    *,
    keep_candidates: bool,
    include_plan: bool,
) -> TraceSummary:
    plan = trace.plan
    response = trace.response
    lexical = trace.lexical
    semantic = trace.semantic
    fused = trace.fused
    reranked = trace.reranked

    warning_codes = tuple(warning.code.value for warning in response.warnings)
    degraded = any(warning.code in _DEGRADED_CODES for warning in response.warnings)

    return TraceSummary(
        request_id=plan.context.request_id,
        audit_id=plan.context.audit_id,
        account_id=plan.scope.account_id,
        client_id=plan.context.client_id,
        plan_fingerprint=plan.fingerprint,
        mode_requested=plan.mode_requested.value,
        mode_effective=plan.mode_effective.value,
        strategy=plan.strategy.value,
        index_version=plan.versions.index_version,
        embedding_model=plan.versions.embedding_model,
        embedding_version=plan.versions.embedding_version,
        reranker_version=plan.versions.reranker,
        filter_names=_filter_names(plan.filters),
        filter_sizes=_filter_sizes(plan.filters),
        lexical_count=len(lexical.hits) if lexical is not None else None,
        lexical_exhausted=lexical.exhausted if lexical is not None else None,
        lexical_filter_path=lexical.filter_path if lexical is not None else None,
        lexical_elapsed_ms=lexical.elapsed_ms if lexical is not None else None,
        semantic_count=len(semantic.hits) if semantic is not None else None,
        semantic_complete=semantic.complete if semantic is not None else None,
        semantic_filter_path=semantic.filter_path if semantic is not None else None,
        semantic_scan_limit_hit=(
            semantic.scan_limit_hit if semantic is not None else None
        ),
        semantic_elapsed_ms=semantic.elapsed_ms if semantic is not None else None,
        fused_count=len(fused.candidates) if fused is not None else None,
        lexical_used=fused.lexical_used if fused is not None else None,
        semantic_used=fused.semantic_used if fused is not None else None,
        dropped_by_item_cap=(fused.dropped_by_item_cap if fused is not None else None),
        rerank_applied=reranked.applied if reranked is not None else None,
        rerank_model=reranked.model if reranked is not None else None,
        rerank_candidates_in=(
            reranked.stats.candidates_in if reranked is not None else None
        ),
        rerank_scored=reranked.stats.scored if reranked is not None else None,
        rerank_dropped_missing=(
            reranked.stats.dropped_missing if reranked is not None else None
        ),
        rerank_truncated_passages=(
            reranked.stats.truncated_passages if reranked is not None else None
        ),
        rerank_elapsed_ms=reranked.elapsed_ms if reranked is not None else None,
        result_count=len(response.results),
        warnings=warning_codes,
        degraded=degraded,
        timings_ms=dict(trace.timings_ms),
        returned_chunk_ids=tuple(record.chunk_id for record in response.results),
        returned_item_ids=tuple(record.item_id for record in response.results),
        lexical_candidate_ids=(
            tuple(hit.chunk_id for hit in lexical.hits)
            if keep_candidates and lexical is not None
            else None
        ),
        semantic_candidate_ids=(
            tuple(hit.chunk_id for hit in semantic.hits)
            if keep_candidates and semantic is not None
            else None
        ),
        fused_candidate_ids=(
            tuple(candidate.chunk_id for candidate in fused.candidates)
            if keep_candidates and fused is not None
            else None
        ),
        reranked_candidate_ids=(
            tuple(hit.chunk_id for hit in reranked.ranked)
            if keep_candidates and reranked is not None
            else None
        ),
        plan=plan if include_plan else None,
    )


def _filter_names(filters: ResolvedFilters) -> tuple[str, ...]:
    """Names of the constraints actually set. Never their values."""
    names: list[str] = []
    if filters.senders:
        names.append("sender")
    if filters.recipients:
        names.append("recipient")
    if filters.participants:
        names.append("participant")
    if filters.direction is not None:
        names.append("direction")
    if filters.tags_any:
        names.append("tags")
    if filters.tags_exclude:
        names.append("exclude_tags")
    if filters.has_attachment is not None:
        names.append("has_attachment")
    if filters.thread_of is not None:
        names.append("thread_of")
    if filters.languages:
        names.append("language")
    if filters.sent_from is not None or filters.sent_before is not None:
        names.append("date_range")
    if filters.include_trash_spam:
        names.append("include_trash_spam")
    return tuple(names)


def _filter_sizes(filters: ResolvedFilters) -> dict[str, int]:
    """Sizes of the list-valued constraints. Never their values."""
    sizes: dict[str, int] = {}
    for name, values in (
        ("sender", filters.senders),
        ("recipient", filters.recipients),
        ("participant", filters.participants),
        ("tags", filters.tags_any),
        ("exclude_tags", filters.tags_exclude),
        ("language", filters.languages),
    ):
        if values:
            sizes[name] = len(values)
    return sizes
