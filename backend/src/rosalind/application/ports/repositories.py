"""Persistence ports (interfaces) for repositories.

The concrete implementations live in ``adapters.outbound.persistence`` and
satisfy these protocols structurally.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.orm import Session

from rosalind.application.read_models import PersonProfile
from rosalind.domain.source import Import, ImportFile, SourceAccount

if TYPE_CHECKING:
    from rosalind.adapters.outbound.persistence.models.source import SourceRecord


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


class SourceAccountRepository(Protocol):
    def get(self, db: Session, source_id: uuid.UUID) -> SourceAccount | None: ...

    def get_by_name(self, db: Session, name: str) -> SourceAccount | None: ...

    def get_by_identity(
        self, db: Session, provider: str, account_identifier: str
    ) -> SourceAccount | None: ...

    def list(self, db: Session) -> list[SourceAccount]: ...

    def create(
        self, db: Session, *, provider: str, name: str | None = None
    ) -> SourceAccount: ...

    def update(self, db: Session, account: SourceAccount) -> SourceAccount: ...

    def delete(self, db: Session, source_id: uuid.UUID) -> None: ...


class ImportRepository(Protocol):
    def create(
        self, db: Session, *, source_account_id: uuid.UUID, type_: str
    ) -> Import: ...

    def get(self, db: Session, import_id: uuid.UUID) -> Import | None: ...

    def list(self, db: Session) -> list[Import]: ...

    def complete(
        self,
        db: Session,
        import_id: uuid.UUID,
        *,
        files: Sequence[ImportFile],
        file_count: int,
        total_size: int,
        import_hash: str,
        completed_at: datetime,
    ) -> Import: ...

    def set_processing_status(
        self, db: Session, import_id: uuid.UUID, status: str
    ) -> Import: ...

    def mark_completed(
        self, db: Session, import_id: uuid.UUID, *, completed_at: datetime
    ) -> Import: ...

    def delete(self, db: Session, import_id: uuid.UUID) -> None: ...
