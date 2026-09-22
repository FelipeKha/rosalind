"""Persistence ports (interfaces) for repositories.

The concrete implementations live in ``adapters.outbound.persistence`` and
satisfy these protocols structurally.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.orm import Session

from rosalind.application.read_models import PersonProfile

if TYPE_CHECKING:
    from rosalind.adapters.outbound.persistence.models.source import (
        SourceAccount,
        SourceRecord,
    )


class PersonRepository(Protocol):
    def search(self, db: Session, query: str, limit: int) -> list[PersonProfile]: ...

    def list_all(self, db: Session, limit: int) -> list[PersonProfile]: ...

    def get(self, db: Session, person_id: uuid.UUID) -> PersonProfile | None: ...


class SourceRecordRepository(Protocol):
    def persist(
        self,
        db: Session,
        *,
        source_account: SourceAccount,
        resource_type: str,
        external_id: str,
        payload: dict[str, Any],
        payload_sha256: str,
        source_etag: str | None = None,
        source_updated_at: datetime | None = None,
        import_id: uuid.UUID | None = None,
    ) -> SourceRecord: ...

    def list_for_import(
        self, db: Session, import_id: uuid.UUID
    ) -> list[SourceRecord]: ...
