"""Semantic retrieval result (online search pipeline, step 2.2).

Layer: ``application``. Plain frozen dataclasses with no SQLAlchemy, pgvector,
or PostgreSQL concepts. The concrete outbound adapter
(``adapters.outbound.search.semantic``) produces these from a ``SearchPlan``;
nothing here knows how the vector search was executed.

``distance`` is the engine's cosine distance, preserved exactly. ``rank`` is the
1-based position in the deterministic ordering (``distance ASC, id ASC``), which
later steps (fusion, evaluation) rely on. ``email_id`` is carried so step 3 can
apply its per-message cap without a second lookup.

``complete`` and ``scan_limit_hit`` are the correctness contract: ``complete``
means every matching chunk was considered (the exact path, or a count proved
fewer than ``semantic_k`` exist). ``scan_limit_hit`` means the approximate scan
stopped before finding all qualifying matches. They are *never* inferred from
"we got fewer than K rows" alone.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

SemanticFilterPath = Literal["exact", "ann_iterative"]

__all__ = [
    "SemanticFilterPath",
    "SemanticHit",
    "SemanticResult",
    "SemanticRetrievalError",
]


class SemanticRetrievalError(Exception):
    """Semantic retrieval could not complete (backend failure, timeout).

    The retrieve orchestrator maps this to a ``MODE_DEGRADED`` warning rather
    than failing the whole search, mirroring how Prepare degrades an embedding
    failure to lexical.
    """


@dataclass(frozen=True, slots=True)
class SemanticHit:
    """One ranked chunk produced by semantic retrieval."""

    chunk_id: uuid.UUID
    email_id: uuid.UUID
    rank: int  # 1-based, deterministic (distance ASC, id ASC)
    distance: float  # the engine's cosine distance, unmodified

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rank must be at least 1")


@dataclass(frozen=True, slots=True)
class SemanticResult:
    """What step 2.2 returns: up to ``semantic_k`` ranked chunks plus provenance."""

    hits: tuple[SemanticHit, ...]
    complete: bool  # every matching chunk was considered
    filter_path: SemanticFilterPath  # how the search was executed
    scan_limit_hit: bool  # the ANN scan stopped early and may have missed matches
    warnings: tuple[str, ...] = ()
    elapsed_ms: float = 0.0
