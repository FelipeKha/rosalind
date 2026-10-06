"""Lexical retrieval result (online search pipeline, step 2.1).

Layer: ``application``. Plain frozen dataclasses with no SQLAlchemy, pg_search,
or PostgreSQL concepts. The concrete outbound adapter
(``adapters.outbound.search.lexical``) produces these from a ``SearchPlan``;
nothing here knows how BM25 was executed.

``score`` is the engine's BM25 score, preserved exactly. ``rank`` is the
1-based position in the deterministic ordering (``score DESC, id ASC``), which
later steps (fusion, evaluation) rely on. ``exhausted`` means fewer than
``lexical_k`` chunks matched *in total* — a fact the adapter can only assert
when it has scanned the whole candidate stream, never when a backend failed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

FilterPath = Literal["pushdown", "overfetch"]

__all__ = ["FilterPath", "LexicalHit", "LexicalResult"]


@dataclass(frozen=True, slots=True)
class LexicalHit:
    """One ranked chunk produced by lexical retrieval."""

    chunk_id: uuid.UUID
    rank: int  # 1-based, deterministic (score DESC, id ASC)
    score: float  # the engine's BM25 score, unmodified

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rank must be at least 1")


@dataclass(frozen=True, slots=True)
class LexicalResult:
    """What step 2.1 returns: up to ``lexical_k`` ranked chunks plus provenance."""

    hits: tuple[LexicalHit, ...]
    exhausted: bool
    filter_path: FilterPath
    warnings: tuple[str, ...] = ()
    elapsed_ms: float = 0.0
