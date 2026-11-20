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

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from rosalind.adapters.outbound.persistence import models
from rosalind.application.authz.models import (
    AccessClause,
    EffectiveScope,
    ParticipantTerm,
    PolicyDecision,
)
from rosalind.application.search import SearchPlan

__all__ = [
    "access_conditions",
    "filter_conditions",
    "scope_conditions",
    "scope_nums",
]


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

    conditions.extend(access_conditions(plan))
    return cast(list[ColumnElement[bool]], conditions)


def access_conditions(plan: SearchPlan) -> list[ColumnElement[bool]]:
    """Mandatory predicates from the agent's effective access scope.

    User-requested filters can only narrow the result; they never relax these.
    ``None`` means policy enforcement is off for this plan.
    """
    return scope_conditions(plan.access_scope)


def scope_conditions(
    scope: EffectiveScope | None,
) -> list[ColumnElement[bool]]:
    """Render an effective scope as predicates on ``search.chunk``."""
    if scope is None:
        return []
    if scope.decision is PolicyDecision.DENY_ALL:
        return [false()]

    chunk = models.Chunk
    conditions: list[ColumnElement[bool]] = []

    if not scope.implicit_permit_all:
        conditions.append(
            or_(*[_clause_condition(chunk, clause) for clause in scope.permits])
        )
    for clause in scope.denies:
        conditions.append(~_clause_condition(chunk, clause))

    return conditions


def _clause_condition(chunk, clause: AccessClause) -> ColumnElement[bool]:
    parts: list[ColumnElement[bool]] = []
    if clause.source_account_id is not None:
        parts.append(chunk.source_account_id == clause.source_account_id)
    if clause.sent_from is not None:
        parts.append(chunk.sent_at >= clause.sent_from)
    if clause.sent_before is not None:
        parts.append(chunk.sent_at < clause.sent_before)
    if clause.direction is not None:
        parts.append(chunk.direction == clause.direction)
    parts.extend(_participant_condition(chunk, term) for term in clause.participants)
    if not parts:
        return true()
    return and_(*parts)


def _participant_condition(chunk, term: ParticipantTerm) -> ColumnElement[bool]:
    addresses = sorted(term.addresses)
    if not addresses:
        return false()
    roles = term.roles or frozenset({"from", "to", "cc", "bcc"})
    if roles == frozenset({"from", "to", "cc", "bcc"}):
        return chunk.participant_handles.overlap(addresses)

    columns = {
        "from": chunk.from_handles,
        "to": chunk.to_handles,
        "cc": chunk.cc_handles,
        "bcc": chunk.bcc_handles,
    }
    return or_(
        *[columns[role].overlap(addresses) for role in sorted(roles) if role in columns]
    )
