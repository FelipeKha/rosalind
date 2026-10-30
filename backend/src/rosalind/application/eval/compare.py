"""Compare two runs and report metric deltas with confidence intervals (pure).

Alignment is per question (paired): only questions present in both runs with a
non-null value for the metric contribute. Reports the mean in each run, the
delta, a paired bootstrap confidence interval, and a paired permutation p-value.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from rosalind.application.eval.stats import (
    paired_bootstrap_ci,
    paired_permutation_pvalue,
)

__all__ = ["MetricDelta", "RunSummary", "compare_runs"]

# metric key -> per-question column name (None means the "hit" boolean)
_METRICS: dict[str, str | None] = {
    "recall_lexical": "recall_lexical",
    "recall_semantic": "recall_semantic",
    "recall_fused": "recall_fused",
    "recall_reranked": "recall_reranked",
    "recall_window": "recall_window",
    "mrr": "mrr",
    "ndcg@10": "ndcg_at_10",
    "hit_rate": None,
}


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    question_rows: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class MetricDelta:
    metric: str
    a: float
    b: float
    delta: float
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    pairs: int


def compare_runs(
    run_a: RunSummary,
    run_b: RunSummary,
    *,
    metrics: list[str] | None = None,
    n: int = 10000,
    alpha: float = 0.05,
    seed: int = 0,
) -> list[MetricDelta]:
    results: list[MetricDelta] = []
    for metric in metrics or list(_METRICS):
        column = _METRICS.get(metric, metric)
        series_a = _series(run_a.question_rows, column)
        series_b = _series(run_b.question_rows, column)
        shared = sorted(set(series_a) & set(series_b))
        if len(shared) < 2:
            continue
        values_a = [series_a[qid] for qid in shared]
        values_b = [series_b[qid] for qid in shared]
        ci = paired_bootstrap_ci(values_a, values_b, n=n, alpha=alpha, seed=seed)
        p_value = paired_permutation_pvalue(values_a, values_b, n=n, seed=seed)
        results.append(
            MetricDelta(
                metric=metric,
                a=mean(values_a),
                b=mean(values_b),
                delta=mean(values_a) - mean(values_b),
                ci_low=ci[0] if ci else None,
                ci_high=ci[1] if ci else None,
                p_value=p_value,
                pairs=len(shared),
            )
        )
    return results


def _series(rows: list[dict[str, Any]], column: str | None) -> dict[str, float]:
    series: dict[str, float] = {}
    for row in rows:
        question_id = row["question_id"]
        if column is None:
            series[question_id] = 1.0 if row["hit"] else 0.0
        elif row.get(column) is not None:
            series[question_id] = float(row[column])
    return series
