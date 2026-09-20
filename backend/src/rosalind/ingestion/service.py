"""Import lifecycle orchestration and person ingestion."""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind import models
from rosalind.canonicalization.person import CanonicalizationResult, canonicalize
from rosalind.ingestion import manifest
from rosalind.ingestion.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
    InvalidPayloadError,
)
from rosalind.ingestion.google.models import (
    GOOGLE_PERSON_RESOURCE_TYPE,
    GooglePerson,
)
from rosalind.ingestion.google.parser import map_google_person

STATUS_UPLOADING = "uploading"
STATUS_COMPLETED = "completed"


def create_import(db: Session, source: str, type_: str) -> models.Import:
    import_ = models.Import(source=source, type=type_, status=STATUS_UPLOADING)
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
    if import_.status != STATUS_UPLOADING:
        raise InvalidImportStateError(
            f"import {import_id} is in state {import_.status!r}, not {STATUS_UPLOADING!r}"
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
    import_.status = STATUS_COMPLETED
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


def payload_sha256(payload: dict[str, Any]) -> str:
    """Deterministic SHA-256 over the canonical JSON serialization of a payload."""
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ingest_person(
    db: Session,
    source_account: models.SourceAccount,
    payload: dict[str, Any],
) -> CanonicalizationResult:
    """Persist a Google Person payload and canonicalize it.

    The raw record is written *before* parsing/validation so that a malformed or
    provider-changed payload is still retained as evidence; raw persistence and
    canonicalization are separate failure domains.
    """
    if not isinstance(payload, dict):
        raise InvalidPayloadError("provider payload must be a JSON object")

    resource_name = payload.get("resourceName")
    if not resource_name:
        raise InvalidPayloadError("provider payload is missing resourceName")
    external_id = (
        resource_name if isinstance(resource_name, str) else str(resource_name)
    )

    source_record = _persist_source_record(db, source_account, external_id, payload)

    person = GooglePerson.model_validate(payload)
    observation = map_google_person(person)
    result = canonicalize(db, source_account, source_record, observation)
    db.commit()
    return result


def _persist_source_record(
    db: Session,
    source_account: models.SourceAccount,
    external_id: str,
    payload: dict[str, Any],
) -> models.SourceRecord:
    sha = payload_sha256(payload)
    values = {
        "source_account_id": source_account.id,
        "resource_type": GOOGLE_PERSON_RESOURCE_TYPE,
        "external_id": external_id,
        "source_etag": payload.get("etag"),
        "source_updated_at": None,
        "observed_at": models.utcnow(),
        "payload": payload,
        "payload_sha256": sha,
    }
    record_id = db.scalar(
        pg_insert(models.SourceRecord)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_source_record_snapshot")
        .returning(models.SourceRecord.id)
    )
    if record_id is None:
        record_id = db.scalar(
            select(models.SourceRecord.id).where(
                models.SourceRecord.source_account_id == source_account.id,
                models.SourceRecord.resource_type == GOOGLE_PERSON_RESOURCE_TYPE,
                models.SourceRecord.external_id == external_id,
                models.SourceRecord.payload_sha256 == sha,
            )
        )

    db.commit()
    record = db.get(models.SourceRecord, record_id)
    if record is None:
        raise RuntimeError("source record not found after upsert")
    return record
