"""Import lifecycle: creating, completing, listing, and deleting imports.

An import is a discrete ingestion job/dataset bound to a source account. It
tracks two independent dimensions: ``ingestion_status`` (was the data brought
in?) and ``processing_status`` (has it been turned into canonical data?).

Persistence goes through the ``ImportRepository`` port, reached via the injected
``UnitOfWork``; raw object removal goes through the ``ObjectStorage`` port. This
module owns only the lifecycle rules, manifest validation, and the orchestration
between import creation, ingestion, and object storage.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from rosalind.application import manifest
from rosalind.application.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
    UnsupportedImportTypeError,
)
from rosalind.application.ports.object_storage import ObjectStorage
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.services.processing import ProcessingService
from rosalind.application.services.sources import SourceService
from rosalind.domain.source import Import, ImportFile

INGESTION_UPLOADING = "uploading"

IMPORT_TYPE_TAKEOUT = "takeout"
IMPORT_TYPE_API = "api"


class ImportService:
    def __init__(
        self,
        storage: ObjectStorage,
        sources: SourceService,
        processing: ProcessingService,
    ):
        self._storage = storage
        self._sources = sources
        self._processing = processing

    def create_import(self, uow: UnitOfWork, source_name: str, type_: str) -> Import:
        """Create an import, and for API-backed imports ingest it immediately."""
        source = self._sources.resolve_source(uow, source_name)

        if type_ == IMPORT_TYPE_TAKEOUT:
            import_ = uow.imports.create(source_account_id=source.id, type_=type_)
        elif type_ == IMPORT_TYPE_API:
            import_ = uow.imports.create(source_account_id=source.id, type_=type_)
            self._processing.import_api_profile(uow, source, import_)
            import_ = uow.imports.mark_completed(
                import_.id, completed_at=datetime.now(UTC)
            )
        else:
            raise UnsupportedImportTypeError(f"unsupported import type {type_!r}")

        uow.commit()
        return replace(import_, source_name=source.name)

    def complete_import(
        self,
        uow: UnitOfWork,
        import_id: uuid.UUID,
        files: Sequence[manifest.FileEntry],
    ) -> Import:
        import_ = self.get_import(uow, import_id)
        if import_.ingestion_status != INGESTION_UPLOADING:
            raise InvalidImportStateError(
                f"import {import_id} is in state {import_.ingestion_status!r}, "
                f"not {INGESTION_UPLOADING!r}"
            )

        _validate_entries(files)

        domain_files = [
            ImportFile(
                path=entry.path,
                sha256=entry.sha256,
                size=entry.size,
                format=entry.format,
                modified_at=entry.modified_at,
                storage_key=manifest.storage_key(import_id, entry.path),
            )
            for entry in files
        ]

        import_ = uow.imports.complete(
            import_id,
            files=domain_files,
            file_count=len(files),
            total_size=sum(entry.size for entry in files),
            import_hash=manifest.compute_import_hash(
                [(entry.path, entry.sha256) for entry in files]
            ),
            completed_at=datetime.now(UTC),
        )
        uow.commit()
        return import_

    def get_import(self, uow: UnitOfWork, import_id: uuid.UUID) -> Import:
        import_ = uow.imports.get(import_id)
        if import_ is None:
            raise ImportNotFoundError(f"import {import_id} not found")
        return import_

    def list_imports(self, uow: UnitOfWork) -> list[Import]:
        return uow.imports.list()

    def delete_import(self, uow: UnitOfWork, import_id: uuid.UUID) -> None:
        """Delete an import, removing its raw objects before the import row."""
        import_ = uow.imports.get(import_id)
        if import_ is None:
            raise ImportNotFoundError(f"import {import_id} not found")
        self._storage.delete_objects([f.storage_key for f in import_.files])
        uow.imports.delete(import_id)
        uow.commit()


def _validate_entries(
    files: Sequence[manifest.FileEntry],
) -> None:
    seen: set[str] = set()

    for entry in files:
        manifest.validate_path(entry.path)
        manifest.validate_sha256(entry.sha256)
        if entry.size < 0:
            raise InvalidManifestError(
                f"file size must be non-negative: {entry.size!r}"
            )
        if entry.path in seen:
            raise InvalidManifestError(f"duplicate file path: {entry.path!r}")
        seen.add(entry.path)
