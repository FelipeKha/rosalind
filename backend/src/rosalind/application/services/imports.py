"""Import lifecycle: creating, completing, listing, and deleting imports.

An import is a discrete ingestion job/dataset bound to a source account. It
tracks two independent dimensions: ``ingestion_status`` (was the data brought
in?) and ``processing_status`` (has it been turned into canonical data?).

Persistence goes through the ``ImportRepository`` port (injected by the
composition root); this module owns only the lifecycle rules and manifest
validation.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from rosalind.application import manifest
from rosalind.application.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
)
from rosalind.application.ports.repositories import ImportRepository
from rosalind.domain.source import Import, ImportFile, SourceAccount

INGESTION_UPLOADING = "uploading"
INGESTION_COMPLETED = "completed"

IMPORT_TYPE_TAKEOUT = "takeout"
IMPORT_TYPE_API = "api"

_repository: ImportRepository | None = None


def configure(repository: ImportRepository) -> None:
    global _repository
    _repository = repository


def _repo() -> ImportRepository:
    if _repository is None:
        raise RuntimeError("ImportRepository has not been configured")
    return _repository


def create_import(db: Session, source_account: SourceAccount, type_: str) -> Import:
    import_ = _repo().create(db, source_account_id=source_account.id, type_=type_)
    db.commit()
    return import_


def complete_import(
    db: Session,
    import_id: uuid.UUID,
    files: Sequence[manifest.FileEntry],
) -> Import:
    import_ = get_import(db, import_id)
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

    import_ = _repo().complete(
        db,
        import_id,
        files=domain_files,
        file_count=len(files),
        total_size=sum(entry.size for entry in files),
        import_hash=manifest.compute_import_hash(
            [(entry.path, entry.sha256) for entry in files]
        ),
        completed_at=datetime.now(UTC),
    )
    db.commit()
    return import_


def get_import(db: Session, import_id: uuid.UUID) -> Import:
    import_ = _repo().get(db, import_id)
    if import_ is None:
        raise ImportNotFoundError(f"import {import_id} not found")
    return import_


def complete_api_import(db: Session, import_id: uuid.UUID) -> Import:
    import_ = _repo().mark_completed(db, import_id, completed_at=datetime.now(UTC))
    db.commit()
    return import_


def list_imports(db: Session) -> list[Import]:
    return _repo().list(db)


def delete_import(db: Session, import_id: uuid.UUID) -> None:
    import_ = _repo().get(db, import_id)
    if import_ is None:
        raise ImportNotFoundError(f"import {import_id} not found")
    _repo().delete(db, import_id)
    db.commit()


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
