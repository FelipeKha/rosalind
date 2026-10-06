"""Email offline pipeline: stage 1.2 record split.

Cuts an mbox archive into individual messages, stores each message's bytes in
object storage (content-addressed), and records one ``raw.source_record`` per
message. Later pipeline stages (parse, canonicalize, enrich, chunk, embed) will
build on these records.

The split is **idempotent, not resumable**: re-running starts from the top and
relies on content-addressed storage plus the ``raw.source_record`` dedup key to
avoid duplicates.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from rosalind.adapters.inbound.ingestion.email import parse_email
from rosalind.adapters.inbound.ingestion.mbox import iter_messages
from rosalind.application.canonicalization.email_message import (
    EmailCanonicalizationService,
    blob_key,
    build_canonical_email,
)
from rosalind.application.errors import ImportNotFoundError, InvalidImportStateError
from rosalind.application.ports.object_storage import ObjectStorage
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.services.attachment_extraction import (
    AttachmentExtractionService,
)
from rosalind.application.services.chunking import EmailChunkingService
from rosalind.application.services.email_reconciliation import (
    EmailReconciliationService,
)
from rosalind.application.services.enrichment import EmailEnrichmentService
from rosalind.domain.source import ImportFile, SourceAccount

# emails.md §1.2: resource_type for an individual Gmail message. The mbox
# splitter is format-specific, not provider-specific; this value is assigned
# here, at the application layer, and can differ per provider later.
MESSAGE_RESOURCE_TYPE = "gmail.message"

RECORDS_NAMESPACE = "records"

COMMIT_EVERY = 500
PROGRESS_EVERY = 500

NO_MESSAGE_ID_PREFIX = "no-message-id"

STAGE_SPLIT = "split"
STAGE_CANONICALIZE = "canonicalize"
STAGE_RECONCILE = "reconcile"
STAGE_ENRICH = "enrich"
STAGE_ATTACHMENTS = "attachments"
STAGE_CHUNK = "chunk"

ALL_STAGES = frozenset(
    {
        STAGE_SPLIT,
        STAGE_CANONICALIZE,
        STAGE_RECONCILE,
        STAGE_ENRICH,
        STAGE_ATTACHMENTS,
        STAGE_CHUNK,
    }
)


@dataclass(frozen=True)
class PipelineEvent:
    """A progress event emitted while the pipeline runs."""

    stage: str
    file: str | None = None
    total_files: int = 0
    total_bytes: int = 0
    processed: int = 0
    created: int = 0
    reused: int = 0
    failed: int = 0
    processed_bytes: int = 0
    message: str | None = None
    details: dict[str, int] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "file": self.file,
            "total_files": self.total_files,
            "total_bytes": self.total_bytes,
            "processed": self.processed,
            "created": self.created,
            "reused": self.reused,
            "failed": self.failed,
            "processed_bytes": self.processed_bytes,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class PreparedSplit:
    """Validated context for one split run."""

    import_id: uuid.UUID
    account_id: uuid.UUID
    source_account: SourceAccount
    files: tuple[ImportFile, ...]
    total_bytes: int


@dataclass
class _Counters:
    processed: int = 0
    created: int = 0
    reused: int = 0
    failed: int = 0
    processed_bytes: int = 0


def record_key(payload_sha256: str) -> str:
    """Content-addressed object-storage key for a split record's bytes."""
    return f"{RECORDS_NAMESPACE}/{payload_sha256[:2]}/{payload_sha256}"


def fallback_external_id(payload_sha256: str) -> str:
    """Deterministic ``external_id`` for a message with no ``Message-ID``."""
    return f"{NO_MESSAGE_ID_PREFIX}:{payload_sha256}"


def _is_mbox(file: ImportFile) -> bool:
    return file.format == "mbox" or (file.path or "").lower().endswith(".mbox")


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


class EmailProcessingService:
    """Runs the offline email pipeline (split → canonicalize → enrich → chunk)."""

    def __init__(
        self,
        storage: ObjectStorage,
        canonicalizer: EmailCanonicalizationService,
        reconciler: EmailReconciliationService,
        enricher: EmailEnrichmentService | None = None,
        enrich_budget_seconds: float | None = None,
        enrich_batch_size: int = 500,
        attachment_extractor: AttachmentExtractionService | None = None,
        attachment_budget_seconds: float | None = None,
        chunker: EmailChunkingService | None = None,
    ):
        self._storage = storage
        self._canonicalizer = canonicalizer
        self._reconciler = reconciler
        self._enricher = enricher
        self._enrich_budget_seconds = enrich_budget_seconds
        self._enrich_batch_size = enrich_batch_size
        self._attachment_extractor = attachment_extractor
        self._attachment_budget_seconds = attachment_budget_seconds
        self._chunker = chunker

    def prepare(
        self, uow: UnitOfWork, account_id: uuid.UUID, import_id: uuid.UUID
    ) -> PreparedSplit:
        """Validate the import and resolve the mbox files to split.

        Raises before any streaming begins so the caller can return a proper
        HTTP error instead of a broken stream.
        """
        import_ = uow.imports.get(import_id)
        if import_ is None or import_.account_id != account_id:
            raise ImportNotFoundError(f"import {import_id} not found")
        if import_.ingestion_status != "completed":
            raise InvalidImportStateError(
                f"import {import_id} is not completed; nothing to split"
            )
        if import_.source_account_id is None:
            raise InvalidImportStateError(f"import {import_id} has no source account")

        source_account = uow.source_accounts.get(import_.source_account_id)
        if source_account is None:
            raise InvalidImportStateError(
                f"import {import_id} references a missing source account"
            )

        files = tuple(file for file in import_.files if _is_mbox(file))
        total_bytes = sum(file.size for file in files)
        return PreparedSplit(
            import_id=import_id,
            account_id=account_id,
            source_account=source_account,
            files=files,
            total_bytes=total_bytes,
        )

    def run(
        self,
        uow: UnitOfWork,
        prepared: PreparedSplit,
        *,
        stages: set[str] | None = None,
    ) -> Iterator[PipelineEvent]:
        """Run the selected pipeline stages over the prepared import.

        Yields progress events as it goes. Each stage is committed in batches so
        a crash leaves only already-committed (deduplicated) work behind.
        Chunking runs even when the attachment budget ran out (4B budget
        exhaustion skips only 4B's remaining work, never chunk).
        """
        wanted = set(stages) if stages is not None else set(ALL_STAGES)

        def wants(name: str) -> bool:
            return name in wanted

        counters = _Counters()
        if wants(STAGE_SPLIT):
            yield PipelineEvent(
                stage="starting",
                total_files=len(prepared.files),
                total_bytes=prepared.total_bytes,
            )

            for file in prepared.files:
                yield from self._split_file(uow, prepared, file, counters)

            yield PipelineEvent(
                stage="done",
                total_files=len(prepared.files),
                total_bytes=prepared.total_bytes,
                processed=counters.processed,
                created=counters.created,
                reused=counters.reused,
                failed=counters.failed,
                processed_bytes=counters.processed_bytes,
            )

        canonicalize_ok = True
        if wants(STAGE_CANONICALIZE):
            for event in self._canonicalize(uow, prepared):
                if event.stage == "error":
                    canonicalize_ok = False
                yield event

        if wants(STAGE_RECONCILE) and canonicalize_ok:
            yield from self._reconcile(uow, prepared)

        if wants(STAGE_ENRICH) and self._enricher is not None and canonicalize_ok:
            yield from self._enrich(uow, prepared)

        if (
            wants(STAGE_ATTACHMENTS)
            and self._attachment_extractor is not None
            and canonicalize_ok
        ):
            yield from self._extract_attachments(uow, prepared)

        if wants(STAGE_CHUNK) and self._chunker is not None and canonicalize_ok:
            yield from self._chunk(uow, prepared)

    def _extract_attachments(
        self, uow: UnitOfWork, prepared: PreparedSplit
    ) -> Iterator[PipelineEvent]:
        """Extract attachment text (4B) for the whole source account."""
        extractor = self._attachment_extractor
        if extractor is None:
            return
        yield PipelineEvent(stage="extracting_attachments")
        outcome = extractor.extract(
            uow,
            prepared.source_account.id,
            budget_seconds=self._attachment_budget_seconds,
        )
        yield PipelineEvent(
            stage="attachments_extracted",
            processed=outcome.processed,
            details={
                "done": outcome.done,
                "empty": outcome.empty,
                "needs_ocr": outcome.needs_ocr,
                "unsupported": outcome.unsupported,
                "too_large": outcome.too_large,
                "encrypted": outcome.encrypted,
                "failed": outcome.failed,
                "budget_exhausted": outcome.budget_exhausted,
            },
        )

    def _chunk(
        self, uow: UnitOfWork, prepared: PreparedSplit
    ) -> Iterator[PipelineEvent]:
        """Chunk derived text (stage 5) for the whole source account."""
        chunker = self._chunker
        if chunker is None:
            return
        yield PipelineEvent(stage="chunking")
        outcome = chunker.chunk(uow, prepared.source_account.id)
        yield PipelineEvent(
            stage="chunked",
            processed=outcome.emails_synced,
            details={
                "chunks_written": outcome.chunks_written,
                "chunks_unchanged": outcome.chunks_unchanged,
                "skipped_not_ready": outcome.skipped_not_ready,
                "failed": outcome.failed,
            },
        )

    def _enrich(
        self, uow: UnitOfWork, prepared: PreparedSplit
    ) -> Iterator[PipelineEvent]:
        """Enrich clean text/segments/language for the whole source account."""
        enricher = self._enricher
        if enricher is None:
            return
        yield PipelineEvent(stage="enriching")
        outcome = enricher.enrich(
            uow,
            prepared.source_account.id,
            budget_seconds=self._enrich_budget_seconds,
            limit=self._enrich_batch_size,
        )
        yield PipelineEvent(
            stage="enriched",
            processed=outcome.processed,
            details={
                "done": outcome.done,
                "empty": outcome.empty,
                "failed": outcome.failed,
                "budget_exhausted": outcome.budget_exhausted,
            },
        )

    def _reconcile(
        self, uow: UnitOfWork, prepared: PreparedSplit
    ) -> Iterator[PipelineEvent]:
        """Reconcile thread membership across the whole source account."""
        yield PipelineEvent(stage="reconciling")
        result = self._reconciler.reconcile(uow, prepared.source_account.id)
        yield PipelineEvent(
            stage="reconciled",
            details={
                "threads_created": result.threads_created,
                "threads_removed": result.threads_removed,
                "messages_reassigned": result.messages_reassigned,
            },
        )

    def _canonicalize(
        self, uow: UnitOfWork, prepared: PreparedSplit
    ) -> Iterator[PipelineEvent]:
        """Parse and canonicalize each split record into ``core.email_*``.

        Self-handles are resolved *after* the split so raw persistence never
        depends on a self person existing. Missing self-handles emit a clear
        error event rather than discarding any raw evidence.
        """
        self_handles = self._canonicalizer.self_handles(uow, prepared.account_id)
        if not self_handles:
            yield PipelineEvent(
                stage="error",
                message=(
                    "cannot compute message direction: the account has no self "
                    "person with an email address; set it via the self-person "
                    "endpoint and re-run the pipeline"
                ),
            )
            return

        counters = _Counters()
        observed_at = datetime.now(UTC)
        since_commit = 0
        records = uow.source_records.list_for_import(prepared.import_id)

        for record in records:
            counters.processed += 1
            payload_uri = record.payload_uri
            if payload_uri is None:
                counters.failed += 1
                continue
            try:
                with self._download(payload_uri) as path:
                    parsed = parse_email(_read_bytes(path))
                for attachment in parsed.attachments:
                    key = blob_key(attachment.sha256)
                    if not self._storage.exists(key):
                        self._storage.put(key, attachment.data)
                canonical = build_canonical_email(
                    parsed=parsed,
                    source_account=prepared.source_account,
                    source_record=record,
                    self_handles=self_handles,
                    observed_at=observed_at,
                    resource_type=record.resource_type,
                )
                result = self._canonicalizer.canonicalize(uow, canonical)
                if result.status == "skipped":
                    counters.reused += 1
                else:
                    counters.created += 1
                since_commit += 1
                if since_commit >= COMMIT_EVERY:
                    uow.commit()
                    since_commit = 0
            except Exception:  # noqa: BLE001 - per-record quarantine
                uow.rollback()
                since_commit = 0
                counters.failed += 1

            if counters.processed % PROGRESS_EVERY == 0:
                yield self._canonical_event(counters)

        uow.commit()
        yield self._canonical_event(counters, final=True)

    def _canonical_event(
        self, counters: _Counters, *, final: bool = False
    ) -> PipelineEvent:
        return PipelineEvent(
            stage="canonicalized" if final else "canonicalizing",
            processed=counters.processed,
            created=counters.created,
            reused=counters.reused,
            failed=counters.failed,
        )

    def _split_file(
        self,
        uow: UnitOfWork,
        prepared: PreparedSplit,
        file: ImportFile,
        counters: _Counters,
    ) -> Iterator[PipelineEvent]:
        with self._download(file.storage_key) as path:
            since_commit = 0
            for split in iter_messages(path):
                payload_sha256 = hashlib.sha256(split.raw).hexdigest()
                key = record_key(payload_sha256)
                external_id = split.message_id or fallback_external_id(payload_sha256)

                counters.processed += 1
                counters.processed_bytes += len(split.raw)

                try:
                    if not self._storage.exists(key):
                        self._storage.put(key, split.raw)
                    created = uow.source_records.persist_split(
                        source_account=prepared.source_account,
                        resource_type=MESSAGE_RESOURCE_TYPE,
                        external_id=external_id,
                        payload_sha256=payload_sha256,
                        import_id=prepared.import_id,
                        payload_uri=key,
                    )
                    if created:
                        counters.created += 1
                    else:
                        counters.reused += 1
                    since_commit += 1
                    if since_commit >= COMMIT_EVERY:
                        uow.commit()
                        since_commit = 0
                except Exception:  # noqa: BLE001 - per-record quarantine
                    uow.rollback()
                    since_commit = 0
                    counters.failed += 1

                if counters.processed % PROGRESS_EVERY == 0:
                    yield self._event(file, counters)

            uow.commit()

        yield self._event(file, counters)

    def _event(self, file: ImportFile, counters: _Counters) -> PipelineEvent:
        return PipelineEvent(
            stage="splitting",
            file=file.path,
            processed=counters.processed,
            created=counters.created,
            reused=counters.reused,
            failed=counters.failed,
            processed_bytes=counters.processed_bytes,
        )

    @contextmanager
    def _download(self, key: str) -> Iterator[str]:
        """Stream the object at ``key`` to a temporary file and yield its path."""
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as dest:
                self._storage.download(key, dest)
            yield path
        finally:
            os.remove(path)
