"""Persistence for imports and their file manifests.

Mutations flush but do not commit so they can join a larger service-level
transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from rosalind.adapters.outbound.persistence.models.imports import Import as ImportModel
from rosalind.adapters.outbound.persistence.models.imports import (
    ImportFile as ImportFileModel,
)
from rosalind.domain.source import Import, ImportFile


class PostgresImportRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(self, *, source_account_id: uuid.UUID, type_: str) -> Import:
        model = ImportModel(
            source_account_id=source_account_id,
            type=type_,
            ingestion_status="uploading",
            processing_status="pending",
        )
        self._session.add(model)
        self._session.flush()
        return self._to_domain(model)

    def get(self, import_id: uuid.UUID) -> Import | None:
        model = self._session.scalar(
            select(ImportModel)
            .options(
                selectinload(ImportModel.files),
                selectinload(ImportModel.source_account),
            )
            .where(ImportModel.id == import_id)
        )
        return self._to_domain(model) if model is not None else None

    def list(self) -> list[Import]:
        models = self._session.scalars(
            select(ImportModel)
            .options(
                selectinload(ImportModel.files),
                selectinload(ImportModel.source_account),
            )
            .order_by(ImportModel.created_at.desc())
        ).all()
        return [self._to_domain(model) for model in models]

    def complete(
        self,
        import_id: uuid.UUID,
        *,
        files: Sequence[ImportFile],
        file_count: int,
        total_size: int,
        import_hash: str,
        completed_at: datetime,
    ) -> Import:
        model = self._session.get(ImportModel, import_id)
        if model is None:
            raise ValueError(f"import {import_id} not found")

        for file in files:
            model.files.append(
                ImportFileModel(
                    path=file.path,
                    format=file.format,
                    size=file.size,
                    modified_at=file.modified_at,
                    sha256=file.sha256,
                    storage_key=file.storage_key,
                )
            )

        model.file_count = file_count
        model.total_size = total_size
        model.import_hash = import_hash
        model.ingestion_status = "completed"
        model.completed_at = completed_at

        self._session.flush()
        return self._to_domain(model)

    def set_processing_status(self, import_id: uuid.UUID, status: str) -> Import:
        model = self._session.get(ImportModel, import_id)
        if model is None:
            raise ValueError(f"import {import_id} not found")
        model.processing_status = status
        self._session.flush()
        return self._to_domain(model)

    def mark_completed(self, import_id: uuid.UUID, *, completed_at: datetime) -> Import:
        model = self._session.get(ImportModel, import_id)
        if model is None:
            raise ValueError(f"import {import_id} not found")
        model.ingestion_status = "completed"
        model.processing_status = "completed"
        model.completed_at = completed_at
        self._session.flush()
        return self._to_domain(model)

    def delete(self, import_id: uuid.UUID) -> None:
        model = self._session.get(ImportModel, import_id)
        if model is None:
            return
        self._session.delete(model)
        self._session.flush()

    @staticmethod
    def _to_domain(model: ImportModel) -> Import:
        files = tuple(
            ImportFile(
                path=f.path,
                sha256=f.sha256,
                size=f.size,
                format=f.format,
                modified_at=f.modified_at,
                storage_key=f.storage_key,
            )
            for f in model.files
        )
        source = model.source_account
        return Import(
            id=model.id,
            source_account_id=model.source_account_id,
            source_name=source.name if source else None,
            type=model.type,
            ingestion_status=model.ingestion_status,
            processing_status=model.processing_status,
            created_at=model.created_at,
            completed_at=model.completed_at,
            file_count=model.file_count,
            total_size=model.total_size,
            import_hash=model.import_hash,
            files=files,
        )
