"""Import lifecycle: creating, completing, listing, and deleting imports.

An import is a discrete ingestion job/dataset bound to a source account. It
tracks two independent dimensions: ``ingestion_status`` (was the data brought
in?) and ``processing_status`` (has it been turned into canonical data?).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind import models
from rosalind.ingestion import manifest
from rosalind.ingestion.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
)

INGESTION_UPLOADING = "uploading"
INGESTION_COMPLETED = "completed"

IMPORT_TYPE_TAKEOUT = "takeout"
IMPORT_TYPE_API = "api"


def create_import(
    db: Session, source_account: models.SourceAccount, type_: str
) -> models.Import:
    import_ = models.Import(
        source_account_id=source_account.id,
        type=type_,
        ingestion_status=INGESTION_UPLOADING,
        processing_status="pending",
    )
    db.add(import_)
    db.commit()
    db.refresh(import_)
    return import_


def complete_import(
    db: Session,
    import_id: uuid.UUID,
    files: Sequence[manifest.FileEntry],
) -> models.Import:
    import_ = db.get(models.Import, import_id)
    if import_ is None:
        raise ImportNotFoundError(f"import {import_id} not found")
    if import_.ingestion_status != INGESTION_UPLOADING:
        raise InvalidImportStateError(
            f"import {import_id} is in state {import_.ingestion_status!r}, "
            f"not {INGESTION_UPLOADING!r}"
        )

    entries = _validate_entries(files)

    for entry in files:
        import_.files.append(
            models.ImportFile(
                path=entry.path,
                format=entry.format,
                size=entry.size,
                modified_at=entry.modified_at,
                sha256=entry.sha256,
                storage_key=manifest.storage_key(import_id, entry.path),
            )
        )

    import_.file_count = len(files)
    import_.total_size = sum(entry.size for entry in files)
    import_.import_hash = manifest.compute_import_hash(entries)
    import_.ingestion_status = INGESTION_COMPLETED
    import_.completed_at = datetime.now(UTC)

    db.commit()
    db.refresh(import_)
    return import_


def get_import(db: Session, import_id: uuid.UUID) -> models.Import:
    import_ = db.scalar(select(models.Import).where(models.Import.id == import_id))
    if import_ is None:
        raise ImportNotFoundError(f"import {import_id} not found")
    return import_


def list_imports(db: Session) -> list[models.Import]:
    return list(
        db.scalars(
            select(models.Import).order_by(models.Import.created_at.desc())
        ).all()
    )


def delete_import(db: Session, import_id: uuid.UUID) -> None:
    import_ = db.get(models.Import, import_id)
    if import_ is None:
        raise ImportNotFoundError(f"import {import_id} not found")
    db.delete(import_)
    db.commit()


def _validate_entries(
    files: Sequence[manifest.FileEntry],
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
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
        entries.append((entry.path, entry.sha256))

    return entries
