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
    SourceRecord as SourceRecordModel,
)
from rosalind.domain.source import SourceAccount, SourceRecord


class PostgresSourceRecordRepository:
    """Dedup-aware persistence for ``raw.source_record``.

    Identity is ``(source_account, resource_type, external_id, payload_sha256)``;
    an identical re-import therefore reuses the existing row instead of creating
    a new observation.
    """

    def __init__(self, session: Session):
        self._session = session

    def persist(
        self,
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
        record_id = self._session.scalar(
            pg_insert(SourceRecordModel)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_source_record_snapshot")
            .returning(SourceRecordModel.id)
        )
        if record_id is None:
            record_id = self._session.scalar(
                select(SourceRecordModel.id).where(
                    SourceRecordModel.source_account_id == source_account.id,
                    SourceRecordModel.resource_type == resource_type,
                    SourceRecordModel.external_id == external_id,
                    SourceRecordModel.payload_sha256 == payload_sha256,
                )
            )

        self._session.flush()
        record = self._session.get(SourceRecordModel, record_id)
        if record is None:
            raise RuntimeError("source record not found after upsert")
        return self._to_domain(record)

    def list_for_import(self, import_id: uuid.UUID) -> list[SourceRecord]:
        return [
            self._to_domain(record)
            for record in self._session.scalars(
                select(SourceRecordModel).where(
                    SourceRecordModel.import_id == import_id
                )
            ).all()
        ]

    @staticmethod
    def _to_domain(record: SourceRecordModel) -> SourceRecord:
        return SourceRecord(
            id=record.id,
            source_account_id=record.source_account_id,
            resource_type=record.resource_type,
            external_id=record.external_id,
            payload=record.payload,
            payload_sha256=record.payload_sha256,
        )
