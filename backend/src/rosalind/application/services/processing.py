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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from rosalind.application.canonicalization.person import (
    CanonicalizationResult,
    CanonicalizationService,
)
from rosalind.application.errors import InvalidPayloadError, SourceNotFoundError
from rosalind.application.ports.parsers import PersonParser
from rosalind.application.ports.providers import PeopleGateway
from rosalind.application.ports.repositories import (
    ImportRepository,
    SourceRecordRepository,
)
from rosalind.application.services.sources import SourceService
from rosalind.domain.source import Import, SourceAccount, SourceRecord

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


class ProcessingService:
    def __init__(
        self,
        source_records: SourceRecordRepository,
        parsers: Mapping[str, PersonParser],
        person_parser: PersonParser,
        people: PeopleGateway,
        sources: SourceService,
        imports: ImportRepository,
        canonicalizer: CanonicalizationService,
    ):
        self._source_records = source_records
        self._parsers = parsers
        self._person_parser = person_parser
        self._people = people
        self._sources = sources
        self._imports = imports
        self._canonicalizer = canonicalizer

    def ingest_person(
        self,
        db: Session,
        source_account: SourceAccount,
        payload: dict[str, Any],
        import_id: uuid.UUID | None = None,
    ) -> CanonicalizationResult:
        """Persist a provider person payload and canonicalize it."""
        return self._ingest(db, source_account, self._person_parser, payload, import_id)

    def import_api_profile(
        self,
        db: Session,
        source_account: SourceAccount,
        import_: Import,
    ) -> CanonicalizationResult:
        """Fetch the provider API profile and ingest it into the given import."""
        _, credentials = self._sources.load_credentials(db, source_account.id)
        payload = self._people.fetch_profile(credentials)
        return self.ingest_person(db, source_account, payload, import_id=import_.id)

    def process_import(self, db: Session, import_id: uuid.UUID) -> ProcessOutcome:
        """Canonicalize the raw source records produced by an import.

        Idempotent: canonicalization is guarded by database uniqueness constraints,
        so re-processing an import never creates duplicates. Imports whose type has
        no parser yet (e.g. Takeout) report ``unsupported`` and are left pending.
        """
        import_ = self._imports.get(db, import_id)
        if import_ is None:
            raise InvalidPayloadError(f"import {import_id} not found")

        if import_.source_account_id is None:
            return ProcessOutcome(
                result=RESULT_UNSUPPORTED, message="import has no source"
            )

        records = self._source_records.list_for_import(db, import_.id)
        if not records:
            return ProcessOutcome(
                result=RESULT_UNSUPPORTED,
                message="No parser available for this import type.",
            )

        try:
            source_account = self._sources.get_source(db, import_.source_account_id)
        except SourceNotFoundError:
            return ProcessOutcome(
                result=RESULT_UNSUPPORTED, message="source is missing"
            )

        counters = {
            "people_created": 0,
            "facts_created": 0,
            "facts_reused": 0,
            "assertions_created": 0,
        }
        for record in records:
            result = self._canonicalize_record(db, source_account, record)
            if result.created:
                counters["people_created"] += 1
            counters["facts_created"] += result.facts_created
            counters["facts_reused"] += result.facts_reused
            counters["assertions_created"] += result.assertions_created

        self._imports.set_processing_status(db, import_.id, PROCESSING_COMPLETED)
        db.commit()

        return ProcessOutcome(
            result=RESULT_OK,
            people_created=counters["people_created"],
            facts_created=counters["facts_created"],
            facts_reused=counters["facts_reused"],
            assertions_created=counters["assertions_created"],
        )

    def _ingest(
        self,
        db: Session,
        source_account: SourceAccount,
        parser: PersonParser,
        payload: dict[str, Any],
        import_id: uuid.UUID | None,
    ) -> CanonicalizationResult:
        if not isinstance(payload, dict):
            raise InvalidPayloadError("provider payload must be a JSON object")

        source_record = self._source_records.persist(
            db,
            source_account=source_account,
            resource_type=parser.resource_type,
            external_id=parser.external_id(payload),
            payload=payload,
            payload_sha256=payload_sha256(payload),
            source_etag=parser.source_etag(payload),
            import_id=import_id,
        )

        observation = parser.parse(payload)
        result = self._canonicalizer.canonicalize(
            db, source_account, source_record, observation
        )
        db.commit()
        return result

    def _canonicalize_record(
        self,
        db: Session,
        source_account: SourceAccount,
        source_record: SourceRecord,
    ) -> CanonicalizationResult:
        parser = self._parsers.get(source_record.resource_type)
        if parser is None:
            raise InvalidPayloadError(
                f"no canonicalizer for resource type {source_record.resource_type!r}"
            )
        observation = parser.parse(source_record.payload)
        return self._canonicalizer.canonicalize(
            db, source_account, source_record, observation
        )
