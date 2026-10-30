"""Postgres-backed item catalog for eval gold authoring.

Implements the ``ItemCatalog`` port: lists keyable canonical email items for an
account (optionally scoped to one import) and checks which item ids exist. Reads
only; never mutates production data.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.application.eval.models import ItemSummary

__all__ = ["PostgresItemCatalog"]

_DEFAULT_LIMIT = 500


class PostgresItemCatalog:
    def __init__(
        self, session_factory: Callable[[], Session], *, limit: int = _DEFAULT_LIMIT
    ) -> None:
        self._session_factory = session_factory
        self._limit = limit

    def list_items(
        self, account_id: uuid.UUID, import_id: uuid.UUID | None = None
    ) -> list[ItemSummary]:
        with self._session_factory() as session:
            source_ids = self._source_account_ids(session, account_id, import_id)
            if not source_ids:
                return []
            sender = (
                select(models.EmailParticipant.addr)
                .where(
                    models.EmailParticipant.message_id == models.EmailMessage.id,
                    models.EmailParticipant.role == "from",
                )
                .order_by(models.EmailParticipant.seq)
                .limit(1)
                .scalar_subquery()
            )
            rows = session.execute(
                select(
                    models.EmailMessage.id,
                    models.EmailMessage.subject,
                    sender.label("sender"),
                    models.EmailMessage.occurred_at,
                    models.EmailMessage.has_attachments,
                    models.EmailMessage.is_trash_or_spam,
                )
                .where(models.EmailMessage.source_account_id.in_(source_ids))
                .order_by(models.EmailMessage.occurred_at.desc())
                .limit(self._limit)
            ).all()
        return [
            ItemSummary(
                item_id=str(row.id),
                subject=row.subject,
                sender=row.sender,
                occurred_at=row.occurred_at,
                has_attachments=row.has_attachments,
                is_trash_or_spam=row.is_trash_or_spam,
            )
            for row in rows
        ]

    def resolve_message_ids(
        self, account_id: uuid.UUID, message_ids: frozenset[str]
    ) -> dict[str, str]:
        if not message_ids:
            return {}
        with self._session_factory() as session:
            source_ids = self._source_account_ids(session, account_id, None)
            if not source_ids:
                return {}
            rows = session.execute(
                select(models.EmailMessage.message_id, models.EmailMessage.id).where(
                    models.EmailMessage.source_account_id.in_(source_ids),
                    models.EmailMessage.message_id.in_(message_ids),
                )
            ).all()
        resolved: dict[str, str] = {}
        for message_id, item_id in rows:
            resolved.setdefault(str(message_id), str(item_id))
        return resolved

    def existing_item_ids(
        self, account_id: uuid.UUID, item_ids: frozenset[str]
    ) -> frozenset[str]:
        wanted = {_to_uuid(item_id) for item_id in item_ids}
        wanted.discard(None)
        if not wanted:
            return frozenset()
        with self._session_factory() as session:
            source_ids = self._source_account_ids(session, account_id, None)
            if not source_ids:
                return frozenset()
            rows = session.scalars(
                select(models.EmailMessage.id).where(
                    models.EmailMessage.source_account_id.in_(source_ids),
                    models.EmailMessage.id.in_(wanted),
                )
            ).all()
        return frozenset(str(row) for row in rows)

    def _source_account_ids(
        self,
        session: Session,
        account_id: uuid.UUID,
        import_id: uuid.UUID | None,
    ) -> list[uuid.UUID]:
        if import_id is not None:
            import_ = session.get(models.Import, import_id)
            if (
                import_ is None
                or import_.account_id != account_id
                or import_.source_account_id is None
            ):
                return []
            return [import_.source_account_id]
        return list(
            session.scalars(
                select(models.SourceAccount.id).where(
                    models.SourceAccount.account_id == account_id
                )
            ).all()
        )


def _to_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
