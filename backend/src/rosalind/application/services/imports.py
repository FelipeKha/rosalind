"""Import lifecycle: creating, completing, listing, and deleting imports.

An import is a discrete ingestion job/dataset bound to a source account. It
tracks two independent dimensions: ``ingestion_status`` (was the data brought
in?) and ``processing_status`` (has it been turned into canonical data?).

Persistence goes through the ``ImportRepository`` port, reached via the injected
``UnitOfWork``; this module owns only the lifecycle rules and manifest
validation.

These are intentionally module-level functions rather than a class: unlike the
other services, they have no constructor-injected dependencies of their own, so
a class would be pure ceremony.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from rosalind.application import manifest
from rosalind.application.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
)
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.source import Import, ImportFile, SourceAccount

INGESTION_UPLOADING = "uploading"
INGESTION_COMPLETED = "completed"

IMPORT_TYPE_TAKEOUT = "takeout"
IMPORT_TYPE_API = "api"


def create_import(uow: UnitOfWork, source_account: SourceAccount, type_: str) -> Import:
    import_ = uow.imports.create(source_account_id=source_account.id, type_=type_)
    uow.commit()
    return import_


def complete_import(
    uow: UnitOfWork,
    import_id: uuid.UUID,
    files: Sequence[manifest.FileEntry],
) -> Import:
    import_ = get_import(uow, import_id)
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


def get_import(uow: UnitOfWork, import_id: uuid.UUID) -> Import:
    import_ = uow.imports.get(import_id)
    if import_ is None:
        raise ImportNotFoundError(f"import {import_id} not found")
    return import_


def complete_api_import(uow: UnitOfWork, import_id: uuid.UUID) -> Import:
    import_ = uow.imports.mark_completed(import_id, completed_at=datetime.now(UTC))
    uow.commit()
    return import_


def list_imports(uow: UnitOfWork) -> list[Import]:
    return uow.imports.list()


def delete_import(uow: UnitOfWork, import_id: uuid.UUID) -> None:
    import_ = uow.imports.get(import_id)
    if import_ is None:
        raise ImportNotFoundError(f"import {import_id} not found")
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
