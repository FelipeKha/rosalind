"""Embedding domain: spaces, vector validation, and the embeddable rule.

Pure — no SQLAlchemy, no I/O. ``EmbeddingSpace`` describes one model/version and
the shape its output must have; ``validate_vector`` enforces that shape;
``embeddable`` decides which chunks get a vector. The concrete ``search.chunk``
column a space maps to is an adapter concern (see
``adapters.outbound.persistence.embedding_spaces``); ``EmbeddingSpace.column`` is
only the logical column name.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from rosalind.domain.search import ChunkKind

Vector = list[float]

_DTYPES = ("float32", "float16")


@dataclass(frozen=True)
class EmbeddingSpace:
    """One model/version and the shape of the vectors it produces."""

    name: str
    model_id: str
    revision: str
    dtype: str
    dimension: int
    normalized: bool
    column: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")
        if self.dimension <= 0:
            raise ValueError("dimension must be positive")
        if self.dtype not in _DTYPES:
            raise ValueError(f"unsupported dtype {self.dtype!r}")
        if not self.column:
            raise ValueError("column must not be empty")


def embeddable(
    kind: ChunkKind,
    is_trash_or_spam: bool,
    *,
    embed_quotes: bool,
    embed_trash_spam: bool,
) -> bool:
    """Whether a chunk of ``kind``/``is_trash_or_spam`` should be embedded.

    Body and attachment chunks are embedded by default; quoted history only
    when ``embed_quotes`` is set, and trash/spam only when ``embed_trash_spam``
    is set. ``ChunkKind.embeddable`` is the single source of the "embedded by
    default" signal.
    """
    if not (kind.embeddable or embed_quotes):
        return False
    return not (is_trash_or_spam and not embed_trash_spam)


def validate_vector(
    vector: Vector,
    space: EmbeddingSpace,
    *,
    norm_tolerance: float = 1e-3,
) -> None:
    """Raise if ``vector`` does not match ``space`` (length, finite, norm)."""
    if len(vector) != space.dimension:
        raise ValueError(f"vector has {len(vector)} dims, expected {space.dimension}")
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("vector contains non-finite values")
    if space.normalized:
        norm = math.sqrt(sum(value * value for value in vector))
        if abs(norm - 1.0) > norm_tolerance:
            raise ValueError(
                f"vector norm {norm:.6f} is not unit within {norm_tolerance}"
            )
