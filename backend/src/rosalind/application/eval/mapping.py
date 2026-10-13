"""Map an app ``SearchTrace`` onto an eval ``QuestionRun`` (pure)."""

from __future__ import annotations

from typing import Any

from rosalind.application.eval.dataset import QuestionRecord
from rosalind.application.eval.models import (
    FinalResult,
    QuestionRun,
    StageCandidate,
)

__all__ = ["question_run_from_short_circuit", "question_run_from_trace"]

_DEGRADED_CODES = frozenset({"mode_degraded", "retrieval_degraded", "rerank_skipped"})


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


def question_run_from_short_circuit(
    question: QuestionRecord, short_circuit: Any
) -> QuestionRun:
    """Map an app ``ShortCircuit`` onto a (empty) ``QuestionRun``."""
    return QuestionRun(
        question_id=question.id,
        question_type=question.type,
        split=question.split,
        answerable=question.answerable,
        gold=tuple(question.gold),
        warnings=(short_circuit.reason.value,),
        short_circuit=short_circuit.reason.value,
    )
