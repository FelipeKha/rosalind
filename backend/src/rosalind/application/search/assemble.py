"""Context assembly (online search pipeline, step 5).

Layer: ``application``. Pure functions over the ranked window and the fetched
display metadata; no SQLAlchemy, pg_search, pgvector, or HTTP. The concrete
metadata fetchers live in ``adapters.outbound.search`` behind the
``SearchResultDataPort`` / ``MessageListPort`` protocols.

Two paths:

* ``assemble_ranked`` — collapse the ranked chunk window into one result per
  message (or per thread), then page *inside the assembled window* via the
  ranked cursor offset. Grouping must happen before pagination, or messages
  that share a chunk get skipped across page boundaries.
* ``assemble_list`` — the filter-only listing is already one row per message in
  keyset order; assembly only generates snippets and advances the keyset cursor.

``score`` is ``None`` for listing and a real reranker/fused score for ranked
search. Snippets are deterministic and cheap: whitespace-normalize, trim, and
truncate to a bounded number of characters with an ellipsis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from rosalind.application.search.plan import (
    Cursor,
    ListPosition,
    PlanWarning,
    SearchPlan,
)
from rosalind.application.search.request import GroupBy, ResultView
from rosalind.application.search.rerank import RerankResult
from rosalind.application.search.result import (
    MatchedIn,
    SearchCitation,
    SearchResponse,
    SearchResultRecord,
)
from rosalind.domain.search import ChunkKind

if TYPE_CHECKING:
    from rosalind.application.search.ports import CursorCodecPort

__all__ = [
    "AssemblyError",
    "ListResult",
    "SearchResultData",
    "assemble_list",
    "assemble_ranked",
    "make_snippet",
]

_ELLIPSIS = "…"

DEFAULT_MAX_SNIPPET_CHARS = 800


class AssemblyError(Exception):
    """Assembly could not complete (a database failure, not a vanished chunk)."""


@dataclass(frozen=True, slots=True)
class SearchResultData:
    """Presentation metadata for one chunk, fetched by ``SearchResultDataPort``.

    ``display_text`` is ``None`` when the caller asked for metadata only, so a
    ``view=metadata`` search never loads chunk text.
    """

    chunk_id: uuid.UUID
    item_id: uuid.UUID
    thread_id: uuid.UUID | None
    chunk_kind: ChunkKind
    occurred_at: datetime
    sender_handle: str
    subject: str | None
    display_text: str | None
    attachment_name: str | None


@dataclass(frozen=True, slots=True)
class ListResult:
    """The filter-only listing: one row per message in keyset order plus the
    exact total number of matching messages."""

    items: tuple[SearchResultData, ...]
    total: int


def make_snippet(text: str | None, max_chars: int) -> str | None:
    """Whitespace-normalize, trim, and truncate ``text`` to ``max_chars``."""
    if text is None:
        return None
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + _ELLIPSIS


def assemble_ranked(
    plan: SearchPlan,
    reranked: RerankResult,
    result_data: tuple[SearchResultData, ...],
    codec: CursorCodecPort,
    *,
    max_snippet_chars: int = DEFAULT_MAX_SNIPPET_CHARS,
    extra_warnings: tuple[PlanWarning, ...] = (),
) -> SearchResponse:
    """Assemble a ranked search: group the window, then page inside it."""
    window = reranked.ranked[: plan.budgets.window_k]
    score_by_chunk = {hit.chunk_id: hit for hit in window}

    assembled: list[SearchResultRecord] = []
    seen: set[object] = set()
    for data in result_data:
        key = _representative_key(plan, data)
        if key in seen:
            continue
        seen.add(key)
        hit = score_by_chunk.get(data.chunk_id)
        score = (
            (hit.rerank_score if reranked.applied else hit.fused_score)
            if hit is not None
            else None
        )
        assembled.append(_to_record(plan, data, score, max_snippet_chars))

    start = (
        plan.cursor.window_offset
        if plan.cursor is not None and plan.cursor.window_offset is not None
        else 0
    )
    page = assembled[start : start + plan.presentation.limit]
    next_offset = start + len(page)

    next_cursor = None
    if next_offset < len(assembled):
        next_cursor = codec.encode(
            Cursor(fingerprint=plan.fingerprint, window_offset=next_offset),
            account_id=plan.scope.account_id,
            index_version=plan.versions.index_version,
        )

    return SearchResponse(
        results=tuple(page),
        applied_filters=plan.applied(),
        total_estimate=None,
        next_cursor=next_cursor,
        warnings=_dedupe_warnings(plan.warnings + reranked.warnings + extra_warnings),
    )


def assemble_list(
    plan: SearchPlan,
    listed: ListResult,
    codec: CursorCodecPort,
    *,
    max_snippet_chars: int = DEFAULT_MAX_SNIPPET_CHARS,
    extra_warnings: tuple[PlanWarning, ...] = (),
) -> SearchResponse:
    """Assemble a filter-only listing (already keyset-ordered, one row per message)."""
    limit = plan.presentation.limit
    records = tuple(
        _to_record(plan, data, None, max_snippet_chars) for data in listed.items[:limit]
    )

    next_cursor = None
    if len(listed.items) > limit:
        last = listed.items[limit - 1]
        next_cursor = codec.encode(
            Cursor(
                fingerprint=plan.fingerprint,
                list_position=ListPosition(
                    occurred_at=last.occurred_at, email_id=last.item_id
                ),
            ),
            account_id=plan.scope.account_id,
            index_version=plan.versions.index_version,
        )

    return SearchResponse(
        results=records,
        applied_filters=plan.applied(),
        total_estimate=listed.total,
        next_cursor=next_cursor,
        warnings=_dedupe_warnings(plan.warnings + extra_warnings),
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _representative_key(plan: SearchPlan, data: SearchResultData) -> object:
    """The grouping key: message id, or thread id when grouping by thread.

    A message without a thread is its own group (keyed by item id), never merged
    with the other threadless messages.
    """
    if plan.presentation.group_by is GroupBy.THREAD and data.thread_id is not None:
        return ("thread", data.thread_id)
    return ("item", data.item_id)


def _matched_in(kind: ChunkKind) -> MatchedIn:
    return "attachment" if kind is ChunkKind.ATTACHMENT else "body"


def _to_record(
    plan: SearchPlan,
    data: SearchResultData,
    score: float | None,
    max_snippet_chars: int,
) -> SearchResultRecord:
    snippet = (
        make_snippet(data.display_text, max_snippet_chars)
        if plan.presentation.view is ResultView.SNIPPET
        else None
    )
    return SearchResultRecord(
        item_id=data.item_id,
        thread_id=data.thread_id,
        chunk_id=data.chunk_id,
        subject=data.subject,
        sender=data.sender_handle,
        date=data.occurred_at,
        snippet=snippet,
        matched_in=_matched_in(data.chunk_kind),
        score=score,
        citation=SearchCitation(
            item_id=data.item_id,
            chunk_id=data.chunk_id,
            thread_id=data.thread_id,
        ),
    )


def _dedupe_warnings(warnings: tuple[PlanWarning, ...]) -> tuple[PlanWarning, ...]:
    seen: set[tuple[object, ...]] = set()
    deduped: list[PlanWarning] = []
    for warning in warnings:
        key = (
            warning.code,
            warning.message,
            warning.field_name,
            warning.suggestion,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return tuple(deduped)
