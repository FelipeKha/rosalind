"""Shared search predicates for the retrieval adapters.

The lexical (BM25) and semantic (vector) retrievers must operate on the same
candidate universe: identical scope confinement and identical resolved filters.
Both import ``filter_conditions`` and ``scope_nums`` from here so their SQL
predicates cannot drift apart.

The semantic universe is a strict subset of the lexical one — it additionally
requires a fresh, non-null embedding — so the embedding-specific conditions live
in the semantic adapter, not here.
"""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from rosalind.adapters.outbound.persistence import models
from rosalind.application.search import SearchPlan

__all__ = ["filter_conditions", "scope_nums"]


def scope_nums(session: Session, source_account_ids: frozenset[uuid.UUID]) -> list[int]:
    """Resolve scope UUIDs to the ``source_account_num`` integer surrogates."""
    return list(
        session.scalars(
            select(models.SourceAccount.num).where(
                models.SourceAccount.id.in_(source_account_ids)
            )
        ).all()
    )


def filter_conditions(plan: SearchPlan) -> list[ColumnElement[bool]]:
    """Render the resolved filters as SQLAlchemy predicates.

    Lists are OR within a field; fields are AND. ``sender_handle`` is a scalar
    equality against the ``senders`` set; the array columns (recipients,
    participants, tags) use overlap. Excluded tags and the default trash/spam
    exclusion round it out.
    """
    chunk = models.Chunk
    filters = plan.filters
    conditions: list[ColumnElement[bool]] = []

    if filters.senders:
        conditions.append(chunk.sender_handle.in_(sorted(filters.senders)))
    if filters.recipients:
        conditions.append(chunk.recipient_handles.overlap(sorted(filters.recipients)))
    if filters.participants:
        conditions.append(
            chunk.participant_handles.overlap(sorted(filters.participants))
        )
    if filters.direction is not None:
        conditions.append(chunk.direction == filters.direction.value)
    if filters.tags_any:
        conditions.append(chunk.tags.overlap(sorted(filters.tags_any)))
    if filters.tags_exclude:
        conditions.append(~chunk.tags.overlap(sorted(filters.tags_exclude)))
    if filters.has_attachment is not None:
        conditions.append(chunk.has_attachment == filters.has_attachment)
    if filters.thread_id is not None:
        conditions.append(chunk.thread_id == filters.thread_id)
    if filters.languages:
        conditions.append(chunk.language.in_(sorted(filters.languages)))
    if filters.sent_from is not None:
        conditions.append(chunk.sent_at >= filters.sent_from)
    if filters.sent_before is not None:
        conditions.append(chunk.sent_at < filters.sent_before)
    if not filters.include_trash_spam:
        conditions.append(chunk.is_trash_or_spam.is_(False))

    return cast(list[ColumnElement[bool]], conditions)
