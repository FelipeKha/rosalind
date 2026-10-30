"""Failure funnel: the single first stage where a question's gold was lost.

One label per failed question, following the pipeline order:

    not_in_corpus → not_chunked → missed_by_both_branches →
    dropped_by_item_cap → lost_in_fusion → lost_in_rerank → lost_in_assembly

``not_in_corpus`` also covers parse failures (an item that was never
canonicalized), since neither is distinguishable from the trace alone.
"""

from __future__ import annotations

from rosalind.application.eval.dataset import GoldEvidence
from rosalind.application.eval.models import QuestionRun, StageCandidate

__all__ = ["FUNNEL_LABELS", "classify_failure", "gold_in_final"]

FUNNEL_LABELS = (
    "not_in_corpus",
    "not_chunked",
    "missed_by_both_branches",
    "dropped_by_item_cap",
    "lost_in_fusion",
    "lost_in_rerank",
    "lost_in_assembly",
)


def _matches(
    item_id: str, matched_in: str | None, gold: tuple[GoldEvidence, ...]
) -> bool:
    for entry in gold:
        if entry.item_id != item_id:
            continue
        if entry.evidence and entry.evidence.startswith("attachment:"):
            if matched_in == "attachment":
                return True
        else:
            return True
    return False


def gold_in_final(run: QuestionRun) -> bool:
    """True when any assembled result satisfies a gold entry (attachment rule)."""
    return any(
        _matches(result.item_id, result.matched_in, run.gold) for result in run.results
    )


def _items(candidates: tuple[StageCandidate, ...]) -> set[str]:
    return {candidate.item_id for candidate in candidates}


def classify_failure(
    run: QuestionRun,
    *,
    known_item_ids: frozenset[str] | None = None,
    chunked_item_ids: frozenset[str] | None = None,
) -> str | None:
    """Return the funnel label, or ``None`` when the question was answered."""
    if not run.answerable:
        return None
    if gold_in_final(run):
        return None

    gold = run.gold_item_ids
    if known_item_ids is not None and not (gold & known_item_ids):
        return "not_in_corpus"
    if chunked_item_ids is not None and not (gold & chunked_item_ids):
        return "not_chunked"

    branches = _items(run.lexical) | _items(run.semantic)
    if not (gold & branches):
        return "missed_by_both_branches"

    if not (gold & _items(run.fused)):
        return (
            "dropped_by_item_cap" if run.dropped_by_item_cap > 0 else "lost_in_fusion"
        )

    if not (gold & _items(run.reranked)):
        return "lost_in_rerank"

    return "lost_in_assembly"
