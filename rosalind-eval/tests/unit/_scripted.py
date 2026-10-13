"""Shared test helpers: a scripted search executor and run builders."""

from __future__ import annotations

from collections.abc import Iterable

from rosalind_eval.dataset import QuestionRecord
from rosalind_eval.results import FinalResult, QuestionRun, StageCandidate

BUDGETS = {
    "lexical_k": 50,
    "semantic_k": 50,
    "fused_k": 40,
    "rerank_k": 30,
    "window_k": 25,
}


def _candidates(
    items: Iterable[str], *, matched_in: str = "body"
) -> tuple[StageCandidate, ...]:
    return tuple(
        StageCandidate(chunk_id=f"c_{item}", item_id=item, rank=rank, score=1.0)
        for rank, item in enumerate(items, start=1)
    )


def make_run(
    question: QuestionRecord,
    *,
    lexical: Iterable[str] = (),
    semantic: Iterable[str] = (),
    fused: Iterable[str] = (),
    reranked: Iterable[str] = (),
    results: Iterable[str] = (),
    budgets: dict[str, int] | None = None,
    dropped_by_item_cap: int = 0,
    matched_in: str = "body",
    timings_ms: dict[str, float] | None = None,
    **extra: object,
) -> QuestionRun:
    return QuestionRun(
        question_id=question.id,
        question_type=question.type,
        split=question.split,
        answerable=question.answerable,
        gold=tuple(question.gold),
        budgets=dict(budgets or BUDGETS),
        lexical=_candidates(lexical),
        semantic=_candidates(semantic),
        fused=_candidates(fused),
        reranked=_candidates(reranked),
        results=tuple(
            FinalResult(
                item_id=item, chunk_id=f"c_{item}", score=1.0, matched_in=matched_in
            )
            for item in results
        ),
        dropped_by_item_cap=dropped_by_item_cap,
        timings_ms=dict(timings_ms or {"total_ms": 1.0}),
        **extra,  # type: ignore[arg-type]
    )


class ScriptedExecutor:
    """Returns a pre-built ``QuestionRun`` per question id."""

    def __init__(self, runs: dict[str, QuestionRun]) -> None:
        self._runs = runs

    def execute(self, question: QuestionRecord) -> QuestionRun:
        return self._runs[question.id]
