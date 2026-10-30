"""Paired statistics for run comparison (pure Python, no extra dependency).

Bootstrap confidence intervals resample questions with replacement; the paired
permutation test randomly flips the sign of each question's difference to test
whether the mean difference differs from zero. Both are seeded for reproducible
reports. ranx remains available for reference metrics (see ``metrics.ranx_metric``).
"""

from __future__ import annotations

import random
from statistics import mean

__all__ = ["bootstrap_mean_ci", "paired_bootstrap_ci", "paired_permutation_pvalue"]


def bootstrap_mean_ci(
    values: list[float],
    *,
    n: int = 10000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float] | None:
    """Percentile bootstrap CI for the mean of ``values``."""
    if not values:
        return None
    rng = random.Random(seed)  # nosec B311 - statistical resampling, not crypto
    size = len(values)
    means = sorted(mean(rng.choices(values, k=size)) for _ in range(n))
    lower = means[int((alpha / 2) * n)]
    upper = means[int((1 - alpha / 2) * n) - 1]
    return (lower, upper)


def paired_bootstrap_ci(
    a: list[float],
    b: list[float],
    *,
    n: int = 10000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float] | None:
    """Percentile bootstrap CI for the paired mean difference ``a - b``."""
    if not a or len(a) != len(b):
        return None
    differences = [x - y for x, y in zip(a, b, strict=True)]
    return bootstrap_mean_ci(differences, n=n, alpha=alpha, seed=seed)


def paired_permutation_pvalue(
    a: list[float],
    b: list[float],
    *,
    n: int = 10000,
    seed: int = 0,
) -> float | None:
    """Two-sided paired permutation test p-value for mean($a - b$) != 0."""
    if not a or len(a) != len(b):
        return None
    differences = [x - y for x, y in zip(a, b, strict=True)]
    observed = abs(mean(differences))
    if observed == 0.0:
        return 1.0
    rng = random.Random(seed)  # nosec B311 - statistical permutation, not crypto
    extreme = sum(
        1
        for _ in range(n)
        if abs(mean(d * (1 if rng.random() < 0.5 else -1) for d in differences))
        >= observed
    )
    return (extreme + 1) / (n + 1)
