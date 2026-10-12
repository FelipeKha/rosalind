"""Ranking-quality metrics for the gold set (measured, not thresholded)."""

from __future__ import annotations

import math
from collections.abc import Iterable


def recall_at_k(ranked_relevant: Iterable[bool], k: int) -> float:
    """Recall@k for a single query: fraction of relevant results in the top-k.

    ``ranked_relevant`` is one boolean per ranked result (in order) indicating
    relevance; it should include every relevant result the query has.
    """
    flags = list(ranked_relevant)
    total_relevant = sum(1 for hit in flags if hit)
    if total_relevant == 0:
        return 0.0
    return sum(1 for hit in flags[:k] if hit) / total_relevant


def mrr(ranked_relevant: Iterable[bool]) -> float:
    """Reciprocal rank for a single query (0.0 when nothing relevant is found)."""
    for rank, hit in enumerate(ranked_relevant, start=1):
        if hit:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(gains: Iterable[float], k: int) -> float:
    """nDCG@k for a single query given graded relevance gains per ranked result."""
    ranked = list(gains)[:k]
    if not ranked:
        return 0.0
    ideal = sorted(ranked, reverse=True)

    def _dcg(values: list[float]) -> float:
        return sum(gain / math.log2(i + 2) for i, gain in enumerate(values))

    idcg = _dcg(ideal)
    if idcg == 0.0:
        return 0.0
    return _dcg(ranked) / idcg
