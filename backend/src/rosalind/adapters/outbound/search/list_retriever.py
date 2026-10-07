"""Keyset listing adapter for the filter-only ``list`` strategy (step 5).

Implements ``MessageListPort``. One row per email message — the ``seq = 0``
``email_body`` chunk is the message representative, so the dedicated
``chunk_list_idx`` on ``(source_account_num, sent_at, email_id)`` serves the
keyset scan. Paging is keyset (``WHERE (sent_at, email_id) < (?, ?)``), never
``OFFSET``. Scope and filters are always applied; the total count is exact.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.search.filters import filter_conditions, scope_nums
from rosalind.application.search import SearchPlan, SortOrder
from rosalind.application.search.assemble import (
    AssemblyError,
    ListResult,
    SearchResultData,
)
from rosalind.application.search.request import ResultView
from rosalind.domain.search import ChunkKind

__all__ = ["PostgresMessageListRetriever"]


class PostgresMessageListRetriever:
    """Lists messages in keyset order for the ``list`` strategy."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._factory = session_factory

    async def list(self, plan: SearchPlan) -> ListResult:
        try:
            return await asyncio.to_thread(self._list, plan)
        except SQLAlchemyError as exc:
            raise AssemblyError("failed to list messages") from exc

    def _list(self, plan: SearchPlan) -> ListResult:
        chunk = models.Chunk
        message = models.EmailMessage
        descending = plan.presentation.sort is not SortOrder.DATE_ASC

        with self._factory() as session:
            nums = scope_nums(session, plan.scope.source_account_ids)
            conditions = _list_conditions(plan, chunk, nums)

            total = int(
                session.scalar(
                    select(func.count()).select_from(chunk).where(*conditions)
                )
                or 0
            )

            keyset = _keyset_condition(chunk, plan, descending)
            if keyset is not None:
                conditions = [*conditions, keyset]

            include_text = plan.presentation.view is ResultView.SNIPPET
            columns = [
                chunk.id,
                chunk.email_id,
                chunk.thread_id,
                chunk.sent_at,
                chunk.sender_handle,
                message.subject,
            ]
            if include_text:
                columns.append(chunk.text_for_display)

            order = (
                (chunk.sent_at.desc(), chunk.email_id.desc())
                if descending
                else (chunk.sent_at.asc(), chunk.email_id.asc())
            )
            stmt = (
                select(*columns)
                .join(message, message.id == chunk.email_id)
                .where(*conditions)
                .order_by(*order)
                .limit(plan.presentation.limit + 1)
            )
            rows = session.execute(stmt).all()

        items = tuple(_to_data(row, include_text) for row in rows)
        return ListResult(items=items, total=total)


def _list_conditions(
    plan: SearchPlan, chunk, nums: list[int]
) -> list[ColumnElement[bool]]:
    return [
        chunk.source_account_num.in_(nums),
        chunk.chunk_kind == ChunkKind.EMAIL_BODY.value,
        chunk.seq == 0,
        *filter_conditions(plan),
    ]


def _keyset_condition(
    chunk, plan: SearchPlan, descending: bool
) -> ColumnElement[bool] | None:
    position = plan.cursor.list_position if plan.cursor is not None else None
    if position is None:
        return None
    occurred_at, email_id = position.occurred_at, position.email_id
    if descending:
        return or_(
            chunk.sent_at < occurred_at,
            and_(chunk.sent_at == occurred_at, chunk.email_id < email_id),
        )
    return or_(
        chunk.sent_at > occurred_at,
        and_(chunk.sent_at == occurred_at, chunk.email_id > email_id),
    )


def _to_data(row: tuple, include_text: bool) -> SearchResultData:
    return SearchResultData(
        chunk_id=cast(uuid.UUID, row[0]),
        item_id=cast(uuid.UUID, row[1]),
        thread_id=cast(uuid.UUID | None, row[2]),
        chunk_kind=ChunkKind.EMAIL_BODY,
        occurred_at=cast(datetime, row[3]),
        sender_handle=cast(str, row[4]),
        subject=cast(str | None, row[5]),
        display_text=cast(str | None, row[6]) if include_text else None,
        attachment_name=None,
    )
