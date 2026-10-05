"""Attachment text extraction service (4B).

A queue-agnostic, resumable pass: the work finder selects blobs whose derived
row is missing or stale, and each blob is extracted in an isolated subprocess
with time and memory limits. Only the main process writes to the database, in
batches with per-record isolation, so a disconnect stops cleanly at a record
boundary. Permanent failures are only retried on an explicit ``--retry-failed``
or a stage-version change.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess  # nosec B404 - attachment extraction runs in an isolated worker
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass

from rosalind.application.ports.object_storage import ObjectStorage
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.email import AttachmentStatus, AttachmentText

ATTACHMENT_VERSION = "attachments/1"

DEFAULT_LIMIT = 200
COMMIT_EVERY = 50


@dataclass(frozen=True)
class AttachmentOutcome:
    processed: int
    done: int
    empty: int
    needs_ocr: int
    unsupported: int
    too_large: int
    encrypted: int
    failed: int
    budget_exhausted: bool


class AttachmentExtractionService:
    def __init__(
        self,
        storage: ObjectStorage,
        *,
        max_bytes: int,
        max_output_chars: int,
        timeout_seconds: float,
    ):
        self._storage = storage
        self._max_bytes = max_bytes
        self._max_output_chars = max_output_chars
        self._timeout_seconds = timeout_seconds

    @property
    def stage_version(self) -> str:
        return ATTACHMENT_VERSION

    def extract(
        self,
        uow: UnitOfWork,
        source_account_id: uuid.UUID,
        *,
        budget_seconds: float | None = None,
        limit: int = DEFAULT_LIMIT,
        retry_failed: bool = False,
    ) -> AttachmentOutcome:
        deadline = (
            time.monotonic() + budget_seconds if budget_seconds is not None else None
        )
        work = uow.attachment_text.list_blob_work(
            source_account_id=source_account_id,
            stage_version=self.stage_version,
            limit=limit,
            retry_failed=retry_failed,
        )

        counters = {
            "processed": 0,
            "done": 0,
            "empty": 0,
            "needs_ocr": 0,
            "unsupported": 0,
            "too_large": 0,
            "encrypted": 0,
            "failed": 0,
        }
        budget_exhausted = False

        for item in work:
            if deadline is not None and time.monotonic() > deadline:
                budget_exhausted = True
                break
            counters["processed"] += 1

            if item.size > self._max_bytes:
                result = AttachmentText(
                    blob_sha256=item.blob_sha256,
                    status=AttachmentStatus.TOO_LARGE,
                    error=f"size {item.size} exceeds limit {self._max_bytes}",
                )
            else:
                result = self._extract_isolated(item)

            uow.attachment_text.replace_attachment_text(
                result=result, stage_version=self.stage_version
            )
            counters[result.status.value] += 1

            if counters["processed"] % COMMIT_EVERY == 0:
                uow.commit()

        uow.commit()
        return AttachmentOutcome(
            processed=counters["processed"],
            done=counters["done"],
            empty=counters["empty"],
            needs_ocr=counters["needs_ocr"],
            unsupported=counters["unsupported"],
            too_large=counters["too_large"],
            encrypted=counters["encrypted"],
            failed=counters["failed"],
            budget_exhausted=budget_exhausted,
        )

    def _extract_isolated(self, item) -> AttachmentText:
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as dest:
                self._storage.download(item.storage_key, dest)
            return self._run_subprocess(path, item)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _run_subprocess(self, path: str, item) -> AttachmentText:
        command = [
            sys.executable,
            "-m",
            "rosalind.adapters.outbound.enrichment.attachment_worker",
            path,
            item.blob_sha256,
            item.detected_mime or "-",
            item.declared_mime or "-",
            item.filename or "-",
            str(self._max_output_chars),
        ]

        def _limits() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (self._max_bytes + (512 << 20),) * 2)

        try:
            completed = subprocess.run(  # nosec B603 - fixed argv, no shell, blob via temp file
                command,
                capture_output=True,
                timeout=self._timeout_seconds,
                preexec_fn=_limits,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return AttachmentText(
                blob_sha256=item.blob_sha256,
                status=AttachmentStatus.FAILED,
                error="extraction timed out",
            )
        except FileNotFoundError:
            return AttachmentText(
                blob_sha256=item.blob_sha256,
                status=AttachmentStatus.FAILED,
                error="attachment worker unavailable",
            )

        if completed.returncode != 0:
            return AttachmentText(
                blob_sha256=item.blob_sha256,
                status=AttachmentStatus.FAILED,
                error=completed.stderr.decode("utf-8", errors="replace").strip()
                or f"worker exited {completed.returncode}",
            )

        try:
            payload = json.loads(completed.stdout.decode("utf-8"))
            return AttachmentText(
                blob_sha256=payload["blob_sha256"],
                status=AttachmentStatus(payload["status"]),
                text=payload["text"],
                method=payload["method"],
                page_count=payload["page_count"],
                language=payload["language"],
                error=payload["error"],
                truncated=payload["truncated"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            return AttachmentText(
                blob_sha256=item.blob_sha256,
                status=AttachmentStatus.FAILED,
                error=f"bad worker output: {exc}",
            )
