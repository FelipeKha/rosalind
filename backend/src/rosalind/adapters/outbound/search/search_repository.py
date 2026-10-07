"""Read-only persistence adapters for the online search Prepare step.

Each port method runs on its own short-lived session (via ``asyncio.to_thread``)
so the concurrent lookups Prepare issues never share one SQLAlchemy ``Session``
across threads. Scope confinement is explicit: entity and thread resolution are
bounded by the ``Scope`` they are handed, never by a bare ``account_id``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.application.search import ResolvedEntity, Scope
from rosalind.application.search.ports import SearchMetadata

__all__ = ["PostgresSearchRepository"]


class PostgresSearchRepository:
    """Implements the scope, metadata, entity, and thread search ports."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._factory = session_factory

    async def get_scope(self, account_id: uuid.UUID) -> frozenset[uuid.UUID]:
        return await asyncio.to_thread(self._get_scope, account_id)

    def _get_scope(self, account_id: uuid.UUID) -> frozenset[uuid.UUID]:
        with self._factory() as session:
            ids = session.scalars(
                select(models.SourceAccount.id).where(
                    models.SourceAccount.account_id == account_id
                )
            ).all()
        return frozenset(ids)

    async def get_metadata(
        self, source_account_ids: frozenset[uuid.UUID]
    ) -> SearchMetadata:
        return await asyncio.to_thread(self._get_metadata, source_account_ids)

    def _get_metadata(self, source_account_ids: frozenset[uuid.UUID]) -> SearchMetadata:
        chunk = models.Chunk
        with self._factory() as session:
            scope = chunk.source_account_id.in_(source_account_ids)
            bounds = session.execute(
                select(func.min(chunk.sent_at), func.max(chunk.sent_at)).where(scope)
            ).one()
            tags = cast(
                "list[str]",
                session.scalars(
                    select(func.unnest(chunk.tags)).where(scope).distinct()
                ).all(),
            )
            languages_raw = cast(
                "list[str | None]",
                session.scalars(
                    select(chunk.language)
                    .where(scope, chunk.language.is_not(None))
                    .distinct()
                ).all(),
            )
            handles = cast(
                "list[str]",
                session.scalars(
                    select(func.unnest(chunk.participant_handles))
                    .where(scope)
                    .distinct()
                ).all(),
            )
        return SearchMetadata(
            min_sent_at=bounds[0],
            max_sent_at=bounds[1],
            known_tags=frozenset(tags),
            known_languages=frozenset(lang for lang in languages_raw if lang),
            known_handles=frozenset(handles),
        )

    async def resolve(
        self,
        scope: Scope,
        values: tuple[str, ...],
    ) -> tuple[ResolvedEntity, ...]:
        return await asyncio.to_thread(self._resolve, scope, values)

    def _resolve(
        self, scope: Scope, values: tuple[str, ...]
    ) -> tuple[ResolvedEntity, ...]:
        with self._factory() as session:
            return tuple(self._resolve_value(session, scope, value) for value in values)

    def _resolve_value(
        self, session: Session, scope: Scope, value: str
    ) -> ResolvedEntity:
        stripped = value.strip()
        if stripped.lower() == "me":
            return self._resolve_me(session, scope.account_id)
        try:
            person_id = uuid.UUID(stripped)
        except ValueError:
            return ResolvedEntity(requested=value, entity_id=None, handles=frozenset())
        return self._resolve_entity(session, person_id, scope.source_account_ids)

    def _resolve_me(self, session: Session, account_id: uuid.UUID) -> ResolvedEntity:
        handles = session.scalars(
            select(models.PersonEmail.email_normalized)
            .join(
                models.Account,
                models.Account.self_person_id == models.PersonEmail.person_id,
            )
            .where(models.Account.id == account_id)
        ).all()
        return ResolvedEntity(
            requested="me", entity_id=None, handles=frozenset(handles)
        )

    def _resolve_entity(
        self,
        session: Session,
        person_id: uuid.UUID,
        source_account_ids: frozenset[uuid.UUID],
    ) -> ResolvedEntity:
        visible = session.scalar(
            select(func.count())
            .select_from(models.SourceIdentity)
            .where(
                models.SourceIdentity.person_id == person_id,
                models.SourceIdentity.source_account_id.in_(source_account_ids),
            )
        )
        if not visible:
            return ResolvedEntity(
                requested=str(person_id), entity_id=None, handles=frozenset()
            )
        handles = session.scalars(
            select(models.PersonEmail.email_normalized).where(
                models.PersonEmail.person_id == person_id
            )
        ).all()
        return ResolvedEntity(
            requested=str(person_id),
            entity_id=person_id,
            handles=frozenset(handles),
        )

    async def resolve_thread(
        self, scope: Scope, message_id: uuid.UUID
    ) -> uuid.UUID | None:
        return await asyncio.to_thread(self._resolve_thread, scope, message_id)

    def _resolve_thread(self, scope: Scope, message_id: uuid.UUID) -> uuid.UUID | None:
        with self._factory() as session:
            return session.scalar(
                select(models.EmailMessage.thread_id).where(
                    models.EmailMessage.id == message_id,
                    models.EmailMessage.source_account_id.in_(scope.source_account_ids),
                )
            )
