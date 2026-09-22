"""Persistence for raw source records (the immutable evidence layer)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence.models.base import utcnow
from rosalind.adapters.outbound.persistence.models.source import (
    SourceAccount,
    SourceRecord,
)


class PostgresSourceRecordRepository:
    """Dedup-aware persistence for ``raw.source_record``.

    Identity is ``(source_account, resource_type, external_id, payload_sha256)``;
    an identical re-import therefore reuses the existing row instead of creating
    a new observation.
    """

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
    ) -> SourceRecord:
        values = {
            "source_account_id": source_account.id,
            "import_id": import_id,
            "resource_type": resource_type,
            "external_id": external_id,
            "source_etag": source_etag,
            "source_updated_at": source_updated_at,
            "observed_at": utcnow(),
            "payload": payload,
            "payload_sha256": payload_sha256,
        }
        record_id = db.scalar(
            pg_insert(SourceRecord)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_source_record_snapshot")
            .returning(SourceRecord.id)
        )
        if record_id is None:
            record_id = db.scalar(
                select(SourceRecord.id).where(
                    SourceRecord.source_account_id == source_account.id,
                    SourceRecord.resource_type == resource_type,
                    SourceRecord.external_id == external_id,
                    SourceRecord.payload_sha256 == payload_sha256,
                )
            )

        db.commit()
        record = db.get(SourceRecord, record_id)
        if record is None:
            raise RuntimeError("source record not found after upsert")
        return record

    def list_for_import(self, db: Session, import_id: uuid.UUID) -> list[SourceRecord]:
        return list(
            db.scalars(
                select(SourceRecord).where(SourceRecord.import_id == import_id)
            ).all()
        )
