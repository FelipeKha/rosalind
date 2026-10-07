"""Read-only adapter that fetches presentation metadata for assembly (step 5).

Implements ``SearchResultDataPort``. A single query joins the candidate chunks
to their canonical message (for ``subject``) and attachment (for ``filename``),
so a 25-result search is one round trip, never 25. The caller's scope is
re-applied via ``source_account_num``, so a chunk that drifted out of scope
between retrieval and assembly cannot leak through. Chunks that no longer exist
are dropped; a database failure is raised as ``AssemblyError``.

``include_text`` gates whether ``text_for_display`` is selected: a
``view=metadata`` search never loads chunk text, only a ``view=snippet`` one.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.search.filters import scope_nums
from rosalind.application.search import SearchPlan
from rosalind.application.search.assemble import AssemblyError, SearchResultData
from rosalind.domain.search import ChunkKind

__all__ = ["PostgresSearchResultDataRepository"]


class PostgresSearchResultDataRepository:
    """Fetches assembly metadata from ``search.chunk`` on a short-lived session."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._factory = session_factory

    async def get_results(
        self,
        plan: SearchPlan,
        chunk_ids: tuple[uuid.UUID, ...],
        *,
        include_text: bool,
    ) -> tuple[SearchResultData, ...]:
        try:
            return await asyncio.to_thread(self._get, plan, chunk_ids, include_text)
        except SQLAlchemyError as exc:
            raise AssemblyError("failed to fetch result metadata") from exc

    def _get(
        self,
        plan: SearchPlan,
        chunk_ids: tuple[uuid.UUID, ...],
        include_text: bool,
    ) -> tuple[SearchResultData, ...]:
        if not chunk_ids:
            return ()
        chunk = models.Chunk
        message = models.EmailMessage
        attachment = models.EmailAttachment

        with self._factory() as session:
            nums = scope_nums(session, plan.scope.source_account_ids)
            base = [
                chunk.id,
                chunk.email_id,
                chunk.thread_id,
                chunk.chunk_kind,
                chunk.sent_at,
                chunk.sender_handle,
                message.subject,
                attachment.filename,
            ]
            if include_text:
                base.append(chunk.text_for_display)
            stmt = (
                select(*base)
                .join(message, message.id == chunk.email_id)
                .outerjoin(attachment, attachment.id == chunk.attachment_id)
                .where(
                    chunk.id.in_(chunk_ids),
                    chunk.source_account_num.in_(nums),
                )
            )
            rows = session.execute(stmt).all()

        by_id: dict[uuid.UUID, tuple] = {
            cast(uuid.UUID, row[0]): tuple(row) for row in rows
        }

        results: list[SearchResultData] = []
        for chunk_id in chunk_ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            results.append(_to_data(row, include_text))
        return tuple(results)


def _to_data(row: tuple, include_text: bool) -> SearchResultData:
    return SearchResultData(
        chunk_id=cast(uuid.UUID, row[0]),
        item_id=cast(uuid.UUID, row[1]),
        thread_id=cast(uuid.UUID | None, row[2]),
        chunk_kind=ChunkKind(cast(str, row[3])),
        occurred_at=cast(datetime, row[4]),
        sender_handle=cast(str, row[5]),
        subject=cast(str | None, row[6]),
        attachment_name=cast(str | None, row[7]),
        display_text=cast(str | None, row[8]) if include_text else None,
    )
