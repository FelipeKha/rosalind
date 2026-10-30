"""Per-question and aggregate ranking metrics.

Relevance is item-level (gold ``item_id``s), and each stage's candidates are
collapsed to a distinct item ranking preserving first-occurrence order. Metrics:
recall@k per stage (lexical/semantic/fused/reranked/window), MRR and nDCG@10 for
the final assembled order, hit rate, and the branch(es) that found the gold.

The functions are pure and deterministic. ``ranx_metric`` builds the same
recall/MRR/nDCG via ranx and is used by tests to confirm parity with the
reference implementation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean

from rosalind.application.eval.models import QuestionRun, StageCandidate

__all__ = [
    "QuestionMetrics",
    "aggregate",
    "compute_question_metrics",
    "item_order",
    "ranx_metric",
]


@dataclass(frozen=True, slots=True)
class QuestionMetrics:
    recall_lexical: float | None
    recall_semantic: float | None
    recall_fused: float | None
    recall_reranked: float | None
    recall_window: float | None
    mrr: float | None
    ndcg_at_10: float | None
    hit: bool
    branch: str  # lexical_only | semantic_only | both | none


def item_order(candidates: tuple[StageCandidate, ...]) -> list[str]:
    """Distinct item ids in first-occurrence (rank) order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate.item_id not in seen:
            seen.add(candidate.item_id)
            ordered.append(candidate.item_id)
    return ordered


def _recall(ranked: list[str], gold: frozenset[str], k: int) -> float:
    if not gold:
        return 0.0
    return len(set(ranked[:k]) & gold) / len(gold)


def _mrr(ranked: list[str], gold: frozenset[str]) -> float:
    for position, item in enumerate(ranked, start=1):
        if item in gold:
            return 1.0 / position
    return 0.0


def _ndcg_at_k(ranked: list[str], gold: frozenset[str], k: int) -> float:
    if not gold:
        return 0.0
    gains = [1.0 if item in gold else 0.0 for item in ranked[:k]]
    ideal = [1.0] * min(len(gold), k)
    dcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(gains))
    idcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def compute_question_metrics(run: QuestionRun) -> QuestionMetrics:
    """Compute one question's metrics. Non-answerable questions get ``None``."""
    gold = run.gold_item_ids
    lexical = item_order(run.lexical)
    semantic = item_order(run.semantic)
    fused = item_order(run.fused)
    reranked = item_order(run.reranked)
    window = [result.item_id for result in run.results]

    lexical_has = bool(gold & set(lexical))
    semantic_has = bool(gold & set(semantic))
    if lexical_has and semantic_has:
        branch = "both"
    elif lexical_has:
        branch = "lexical_only"
    elif semantic_has:
        branch = "semantic_only"
    else:
        branch = "none"

    if not run.answerable:
        return QuestionMetrics(
            recall_lexical=None,
            recall_semantic=None,
            recall_fused=None,
            recall_reranked=None,
            recall_window=None,
            mrr=None,
            ndcg_at_10=None,
            hit=bool(window),
            branch="none",
        )

    budgets = run.budgets
    return QuestionMetrics(
        recall_lexical=_recall(lexical, gold, budgets.get("lexical_k", len(lexical))),
        recall_semantic=_recall(
            semantic, gold, budgets.get("semantic_k", len(semantic))
        ),
        recall_fused=_recall(fused, gold, budgets.get("fused_k", len(fused))),
        recall_reranked=_recall(reranked, gold, budgets.get("rerank_k", len(reranked))),
        recall_window=_recall(window, gold, budgets.get("window_k", len(window))),
        mrr=_mrr(window, gold),
        ndcg_at_10=_ndcg_at_k(window, gold, 10),
        hit=bool(gold & set(window)),
        branch=branch,
    )


def ranx_metric(
    ranked_items: list[str],
    gold: frozenset[str],
    metric: str,
) -> float:
    """Compute one ranx metric for a single query (reference implementation)."""
    import ranx

    qrels = {"q": {item: 1 for item in gold}}
    run = {"q": {item: 1.0 / (rank + 1) for rank, item in enumerate(ranked_items)}}
    result = ranx.evaluate(qrels, run, [metric])
    try:
        value = result[metric]
    except KeyError, IndexError, TypeError:
        value = result  # ranx returns a scalar for a single metric
    return float(value)


def aggregate(metrics: list[QuestionMetrics]) -> dict[str, float | None]:
    """Mean of each metric across answerable questions (``None``-aware)."""
    answerable = [m for m in metrics if m.recall_fused is not None]
    answerable_rates = [m.hit for m in answerable]
    unanswerable = [m for m in metrics if m.recall_fused is None]

    def _mean(values: list[float]) -> float | None:
        return mean(values) if values else None

    return {
        "recall_lexical": _mean([m.recall_lexical or 0.0 for m in answerable]),
        "recall_semantic": _mean([m.recall_semantic or 0.0 for m in answerable]),
        "recall_fused": _mean([m.recall_fused or 0.0 for m in answerable]),
        "recall_reranked": _mean([m.recall_reranked or 0.0 for m in answerable]),
        "recall_window": _mean([m.recall_window or 0.0 for m in answerable]),
        "mrr": _mean([m.mrr or 0.0 for m in answerable]),
        "ndcg@10": _mean([m.ndcg_at_10 or 0.0 for m in answerable]),
        "hit_rate": _mean([1.0 if h else 0.0 for h in answerable_rates]),
        "unanswerable_return_rate": _mean(
            [1.0 if m.hit else 0.0 for m in unanswerable]
        ),
    }
