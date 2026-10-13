"""Search executors: the port the runner depends on, plus the live adapter.

``SearchExecutor`` is the seam the runner uses to obtain a ``QuestionRun`` for
one dataset question. Tests inject a scripted executor; production uses
``LiveSearchExecutor``, which builds the app's ``SearchService`` and calls the
one ``SearchPipeline`` (principle 1: never reimplement the pipeline).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Protocol

from rosalind_eval.cache import StageCache, cached_run
from rosalind_eval.dataset import QuestionRecord
from rosalind_eval.results import FinalResult, QuestionRun, StageCandidate

__all__ = [
    "LiveSearchExecutor",
    "SearchExecutor",
    "question_run_from_trace",
]

_DEGRADED_CODES = frozenset({"mode_degraded", "retrieval_degraded", "rerank_skipped"})


class SearchExecutor(Protocol):
    def execute(self, question: QuestionRecord) -> QuestionRun:
        """Run the search pipeline for one question."""


class LiveSearchExecutor:
    """Runs questions against the app's real ``SearchService``/``SearchPipeline``."""

    def __init__(
        self,
        service: Any,
        account_id: uuid.UUID,
        *,
        overrides: Any | None = None,
        mode: str | None = None,
        limit: int = 10,
        client_id: str = "rosalind-eval",
        engine: Any | None = None,
        cache: StageCache | None = None,
    ) -> None:
        self._service = service
        self._account_id = account_id
        self._overrides = overrides
        self._mode = mode
        self._limit = limit
        self._client_id = client_id
        self._engine = engine
        self._cache = cache

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
        account_id: uuid.UUID,
        *,
        overrides: Any | None = None,
        mode: str | None = None,
        limit: int = 10,
        cache: StageCache | None = None,
    ) -> LiveSearchExecutor:
        """Wire the app's search service from a database URL."""
        from rosalind.adapters import composition
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(database_url)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        service = composition.build_search_service(factory)
        return cls(
            service,
            account_id,
            overrides=overrides,
            mode=mode,
            limit=limit,
            engine=engine,
            cache=cache,
        )

    def execute(self, question: QuestionRecord) -> QuestionRun:
        from rosalind.application.search import (
            GroupBy,
            ResultView,
            SearchMode,
            SearchRequest,
            ShortCircuit,
            SortOrder,
        )
        from rosalind.application.services.search import PrepareContext

        request = SearchRequest(
            query=question.query,
            keywords=question.keywords,
            filters=question.filters.to_search_request_filters(),
            sort=SortOrder.RELEVANCE,
            group_by=GroupBy.MESSAGE,
            view=ResultView.METADATA,
            limit=self._limit,
            cursor=None,
            mode=SearchMode(self._mode) if self._mode else SearchMode.HYBRID,
        )
        context = PrepareContext(account_id=self._account_id, client_id=self._client_id)
        prepared = asyncio.run(self._service.prepare(context, request))
        if isinstance(prepared, ShortCircuit):
            return _from_short_circuit(question, prepared)
        if self._cache is not None:
            trace, _ = asyncio.run(
                cached_run(
                    self._service.run,
                    prepared,
                    self._cache,
                    overrides=self._overrides,
                )
            )
            return question_run_from_trace(question, trace)
        trace = asyncio.run(
            self._service.run(prepared, trace_level="full", overrides=self._overrides)
        )
        return question_run_from_trace(question, trace)

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()


def question_run_from_trace(question: QuestionRecord, trace: Any) -> QuestionRun:
    """Map an app ``SearchTrace`` onto a ``QuestionRun``."""
    plan = trace.plan
    fused_candidates = trace.fused.candidates if trace.fused is not None else ()
    item_by_chunk = {str(c.chunk_id): str(c.email_id) for c in fused_candidates}
    warning_codes = tuple(warning.code.value for warning in trace.response.warnings)

    lexical = tuple(
        StageCandidate(str(hit.chunk_id), str(hit.email_id), hit.rank, hit.score)
        for hit in (trace.lexical.hits if trace.lexical is not None else ())
    )
    semantic = tuple(
        StageCandidate(str(hit.chunk_id), str(hit.email_id), hit.rank, hit.distance)
        for hit in (trace.semantic.hits if trace.semantic is not None else ())
    )
    fused = tuple(
        StageCandidate(str(c.chunk_id), str(c.email_id), c.fused_rank, c.fused_score)
        for c in fused_candidates
    )
    reranked = tuple(
        StageCandidate(
            str(hit.chunk_id),
            item_by_chunk.get(str(hit.chunk_id), ""),
            hit.rerank_rank,
            hit.rerank_score,
        )
        for hit in (trace.reranked.ranked if trace.reranked is not None else ())
    )
    results = tuple(
        FinalResult(
            str(record.item_id), str(record.chunk_id), record.score, record.matched_in
        )
        for record in trace.response.results
    )
    versions = plan.versions
    semantic_result = trace.semantic
    return QuestionRun(
        question_id=question.id,
        question_type=question.type,
        split=question.split,
        answerable=question.answerable,
        gold=tuple(question.gold),
        plan_fingerprint=plan.fingerprint,
        mode_effective=plan.mode_effective.value,
        index_version=versions.index_version,
        embedding_model=versions.embedding_model,
        embedding_version=versions.embedding_version,
        reranker_version=versions.reranker,
        budgets={
            "lexical_k": plan.budgets.lexical_k,
            "semantic_k": plan.budgets.semantic_k,
            "fused_k": plan.budgets.fused_k,
            "rerank_k": plan.budgets.rerank_k,
            "window_k": plan.budgets.window_k,
        },
        lexical=lexical,
        semantic=semantic,
        fused=fused,
        reranked=reranked,
        results=results,
        dropped_by_item_cap=(
            trace.fused.dropped_by_item_cap if trace.fused is not None else 0
        ),
        lexical_used=bool(trace.fused and trace.fused.lexical_used),
        semantic_used=bool(trace.fused and trace.fused.semantic_used),
        rerank_applied=bool(trace.reranked and trace.reranked.applied),
        semantic_complete=(
            semantic_result.complete if semantic_result is not None else None
        ),
        semantic_filter_path=(
            semantic_result.filter_path if semantic_result is not None else None
        ),
        semantic_scan_limit_hit=(
            semantic_result.scan_limit_hit if semantic_result is not None else None
        ),
        warnings=warning_codes,
        degraded=any(code in _DEGRADED_CODES for code in warning_codes),
        timings_ms=dict(trace.timings_ms),
    )


def _from_short_circuit(question: QuestionRecord, short_circuit: Any) -> QuestionRun:
    return QuestionRun(
        question_id=question.id,
        question_type=question.type,
        split=question.split,
        answerable=question.answerable,
        gold=tuple(question.gold),
        warnings=(short_circuit.reason.value,),
        short_circuit=short_circuit.reason.value,
    )
