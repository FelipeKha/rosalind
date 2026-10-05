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

from rosalind.adapters.inbound.ingestion.mbox import iter_messages
from rosalind.application.errors import ImportNotFoundError, InvalidImportStateError
from rosalind.application.ports.object_storage import ObjectStorage
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.source import ImportFile, SourceAccount

# emails.md §1.2: resource_type for an individual Gmail message. The mbox
# splitter is format-specific, not provider-specific; this value is assigned
# here, at the application layer, and can differ per provider later.
MESSAGE_RESOURCE_TYPE = "gmail.message"

RECORDS_NAMESPACE = "records"

COMMIT_EVERY = 500
PROGRESS_EVERY = 500

NO_MESSAGE_ID_PREFIX = "no-message-id"


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
        }


@dataclass(frozen=True)
class PreparedSplit:
    """Validated context for one split run."""

    import_id: uuid.UUID
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


class EmailProcessingService:
    """Runs the offline email pipeline (currently only the record split stage)."""

    def __init__(self, storage: ObjectStorage):
        self._storage = storage

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
            source_account=source_account,
            files=files,
            total_bytes=total_bytes,
        )

    def run(self, uow: UnitOfWork, prepared: PreparedSplit) -> Iterator[PipelineEvent]:
        """Split the prepared mbox files into raw source records.

        Yields progress events as it goes. Each message is committed in batches
        so a crash leaves only already-committed (deduplicated) work behind.
        """
        counters = _Counters()
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
