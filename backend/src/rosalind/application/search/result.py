"""Assembled search response contracts (online search pipeline, step 5).

Layer: ``application``. Plain frozen dataclasses with no Pydantic, SQLAlchemy,
or provider imports (DESIGN.md section 4: Pydantic is for API boundaries only).
The MCP/REST adapters map ``SearchResponse`` onto their own wire models.

``score`` is ``float | None``, never a fabricated ``0.0``: ``None`` means the
strategy produced no ranking (filter-only listing), while a real value means
the raw reranker or fused score. The score is for ranking/diagnostics, not a
probability, and is preserved exactly as the upstream stage produced it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from rosalind.application.search.plan import PlanWarning

__all__ = ["MatchedIn", "SearchCitation", "SearchResponse", "SearchResultRecord"]

MatchedIn = Literal["body", "attachment"]


@dataclass(frozen=True, slots=True)
class SearchCitation:
    """The passage that caused a message to be returned (for ``get_context``)."""

    item_id: uuid.UUID
    chunk_id: uuid.UUID
    thread_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class SearchResultRecord:
    """One visible result: one email message (or one thread) with its
    representative chunk, display metadata, and an optional snippet."""

    item_id: uuid.UUID
    thread_id: uuid.UUID | None
    chunk_id: uuid.UUID
    subject: str | None
    sender: str  # the from address (normalized handle)
    date: datetime
    snippet: str | None
    matched_in: MatchedIn
    score: float | None
    citation: SearchCitation


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """What step 5 returns: a bounded, deterministic, scope-checked page."""

    results: tuple[SearchResultRecord, ...]
    applied_filters: dict[str, object]
    total_estimate: int | None
    next_cursor: str | None
    warnings: tuple[PlanWarning, ...]
