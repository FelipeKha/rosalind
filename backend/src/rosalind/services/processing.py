"""Processing: turn ingested raw records into canonical data.

Owns the orchestration between raw persistence and canonicalization. The raw
record is written *before* parsing/validation so a malformed or provider-changed
payload is still retained as evidence; raw persistence and canonicalization are
separate failure domains.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind import models
from rosalind.canonicalization.person import CanonicalizationResult, canonicalize
from rosalind.ingestion.errors import InvalidPayloadError
from rosalind.ingestion.google.models import (
    GOOGLE_PERSON_RESOURCE_TYPE,
    GooglePerson,
)
from rosalind.ingestion.google.parser import map_google_person

PROCESSING_PENDING = "pending"
PROCESSING_COMPLETED = "completed"
PROCESSING_FAILED = "failed"

RESULT_OK = "ok"
RESULT_UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ProcessOutcome:
    """Summary of one ``process`` operation on an import."""

    result: str
    message: str | None = None
    people_created: int = 0
    facts_created: int = 0
    facts_reused: int = 0
    assertions_created: int = 0


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
    import_id: uuid.UUID | None = None,
) -> CanonicalizationResult:
    """Persist a Google Person payload and canonicalize it."""
    if not isinstance(payload, dict):
        raise InvalidPayloadError("provider payload must be a JSON object")

    resource_name = payload.get("resourceName")
    if not resource_name:
        raise InvalidPayloadError("provider payload is missing resourceName")
    external_id = (
        resource_name if isinstance(resource_name, str) else str(resource_name)
    )

    source_record = _persist_source_record(
        db, source_account, external_id, payload, import_id
    )

    person = GooglePerson.model_validate(payload)
    observation = map_google_person(person)
    result = canonicalize(db, source_account, source_record, observation)
    db.commit()
    return result


def import_api_profile(
    db: Session,
    source_account: models.SourceAccount,
    import_: models.Import,
) -> CanonicalizationResult:
    """Fetch the People API profile and ingest it into the given import."""
    from rosalind.providers.google import people as google_people
    from rosalind.services import sources as source_service

    _, credentials = source_service.load_credentials(db, source_account.id)
    payload = google_people.fetch_profile(credentials)
    return ingest_person(db, source_account, payload, import_id=import_.id)


def process_import(db: Session, import_id: uuid.UUID) -> ProcessOutcome:
    """Canonicalize the raw source records produced by an import.

    Idempotent: canonicalization is guarded by database uniqueness constraints,
    so re-processing an import never creates duplicates. Imports whose type has
    no parser yet (e.g. Takeout) report ``unsupported`` and are left pending.
    """
    import_ = db.get(models.Import, import_id)
    if import_ is None:
        raise InvalidPayloadError(f"import {import_id} not found")

    if import_.source_account_id is None:
        return ProcessOutcome(result=RESULT_UNSUPPORTED, message="import has no source")

    records = db.scalars(
        select(models.SourceRecord).where(models.SourceRecord.import_id == import_.id)
    ).all()
    if not records:
        return ProcessOutcome(
            result=RESULT_UNSUPPORTED,
            message="No parser available for this import type.",
        )

    source_account = db.get(models.SourceAccount, import_.source_account_id)
    if source_account is None:
        return ProcessOutcome(result=RESULT_UNSUPPORTED, message="source is missing")

    counters = {
        "people_created": 0,
        "facts_created": 0,
        "facts_reused": 0,
        "assertions_created": 0,
    }
    for record in records:
        result = _canonicalize_record(db, source_account, record)
        if result.created:
            counters["people_created"] += 1
        counters["facts_created"] += result.facts_created
        counters["facts_reused"] += result.facts_reused
        counters["assertions_created"] += result.assertions_created

    import_.processing_status = PROCESSING_COMPLETED
    db.commit()

    return ProcessOutcome(
        result=RESULT_OK,
        people_created=counters["people_created"],
        facts_created=counters["facts_created"],
        facts_reused=counters["facts_reused"],
        assertions_created=counters["assertions_created"],
    )


def _canonicalize_record(
    db: Session,
    source_account: models.SourceAccount,
    source_record: models.SourceRecord,
) -> CanonicalizationResult:
    if source_record.resource_type == GOOGLE_PERSON_RESOURCE_TYPE:
        person = GooglePerson.model_validate(source_record.payload)
        observation = map_google_person(person)
        return canonicalize(db, source_account, source_record, observation)
    raise InvalidPayloadError(
        f"no canonicalizer for resource type {source_record.resource_type!r}"
    )


def _persist_source_record(
    db: Session,
    source_account: models.SourceAccount,
    external_id: str,
    payload: dict[str, Any],
    import_id: uuid.UUID | None,
) -> models.SourceRecord:
    sha = payload_sha256(payload)
    values = {
        "source_account_id": source_account.id,
        "import_id": import_id,
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
