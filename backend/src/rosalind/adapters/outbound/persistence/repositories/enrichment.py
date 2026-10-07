"""Persistence for the enrich stage's derived text.

The only module that talks SQL for the derived write path. ``list_email_work``
and ``list_blob_work`` are the work finders; ``replace_email_text`` and
``replace_attachment_text`` replace a row in place (no version history — the
evidence lives in ``core`` and ``raw``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.models.base import utcnow
from rosalind.application.ports.repositories import (
    AttachmentTextWorkItem,
    EmailTextWorkItem,
)
from rosalind.domain.email import AttachmentText, EmailText

# Terminal statuses that a run only retries on an explicit --retry-failed (or a
# stage/input change, which the work finder already handles).
_RETRYABLE_FAILURES = ("failed", "unsupported", "too_large")


class PostgresEmailEnrichmentRepository:
    def __init__(self, session: Session):
        self._session = session

    def list_email_work(
        self,
        *,
        source_account_id: uuid.UUID,
        stage_version: str,
        limit: int,
        retry_failed: bool = False,
    ) -> list[EmailTextWorkItem]:
        stale = (
            models.EmailText.email_id.is_(None)
            | models.EmailText.stage_version.is_distinct_from(stage_version)
            | models.EmailText.input_sha256.is_distinct_from(
                models.EmailMessage.content_sha256
            )
        )
        if retry_failed:
            stale = stale | (models.EmailText.status == "failed")

        stmt = (
            select(
                models.EmailMessage.id,
                models.EmailMessage.text_plain,
                models.EmailMessage.text_html,
                models.EmailMessage.content_sha256,
            )
            .outerjoin(
                models.EmailText,
                models.EmailText.email_id == models.EmailMessage.id,
            )
            .where(
                models.EmailMessage.source_account_id == source_account_id,
                stale,
            )
            .order_by(models.EmailMessage.id)
            .limit(limit)
        )
        rows = self._session.execute(stmt).all()
        return [
            EmailTextWorkItem(
                email_id=email_id,
                text_plain=text_plain,
                text_html=text_html,
                content_sha256=content_sha256,
            )
            for email_id, text_plain, text_html, content_sha256 in rows
        ]

    def replace_email_text(
        self,
        *,
        email_id: uuid.UUID,
        text: EmailText,
        status: str,
        error: str | None,
        stage_version: str,
        input_sha256: str | None,
        segments_digest: str | None,
    ) -> None:
        now = utcnow()
        values = {
            "email_id": email_id,
            "clean_text": text.clean_text,
            "clean_method": text.clean_method.value,
            "status": status,
            "error": error,
            "stage_version": stage_version,
            "input_sha256": input_sha256,
            "segments_digest": segments_digest,
            "created_at": now,
            "updated_at": now,
        }
        self._session.execute(
            pg_insert(models.EmailText)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[models.EmailText.email_id],
                set_={
                    "clean_text": values["clean_text"],
                    "clean_method": values["clean_method"],
                    "status": values["status"],
                    "error": values["error"],
                    "stage_version": values["stage_version"],
                    "input_sha256": values["input_sha256"],
                    "segments_digest": values["segments_digest"],
                    "updated_at": now,
                },
            )
        )

        self._session.execute(
            delete(models.EmailSegment).where(models.EmailSegment.email_id == email_id)
        )
        for segment in text.segments:
            self._session.add(
                models.EmailSegment(
                    email_id=email_id,
                    seq=segment.seq,
                    kind=segment.kind.value,
                    start_offset=segment.start_offset,
                    end_offset=segment.end_offset,
                    language=segment.language,
                    language_confidence=segment.language_confidence,
                    quote_depth=segment.quote_depth,
                    attribution_raw=segment.attribution_raw,
                    quoted_author=segment.quoted_author,
                    quoted_at=segment.quoted_at,
                )
            )


class PostgresAttachmentTextRepository:
    def __init__(self, session: Session):
        self._session = session

    def list_blob_work(
        self,
        *,
        source_account_id: uuid.UUID,
        stage_version: str,
        limit: int,
        retry_failed: bool = False,
    ) -> list[AttachmentTextWorkItem]:
        stale = models.AttachmentText.blob_sha256.is_(
            None
        ) | models.AttachmentText.stage_version.is_distinct_from(stage_version)
        if retry_failed:
            stale = stale | models.AttachmentText.status.in_(_RETRYABLE_FAILURES)

        stmt = (
            select(
                models.EmailAttachment.sha256,
                models.EmailAttachment.storage_key,
                models.EmailAttachment.size,
                models.EmailAttachment.filename,
                models.EmailAttachment.declared_mime,
                models.EmailAttachment.detected_mime,
            )
            .join(
                models.EmailMessage,
                models.EmailMessage.id == models.EmailAttachment.message_id,
            )
            .outerjoin(
                models.AttachmentText,
                models.AttachmentText.blob_sha256 == models.EmailAttachment.sha256,
            )
            .where(
                models.EmailMessage.source_account_id == source_account_id,
                models.EmailAttachment.disposition != "inline",
                stale,
            )
            .distinct()
            .order_by(models.EmailAttachment.sha256)
            .limit(limit)
        )
        rows = self._session.execute(stmt).all()
        return [
            AttachmentTextWorkItem(
                blob_sha256=sha256,
                storage_key=storage_key,
                size=size,
                filename=filename,
                declared_mime=declared_mime,
                detected_mime=detected_mime,
            )
            for sha256, storage_key, size, filename, declared_mime, detected_mime in rows
        ]

    def replace_attachment_text(
        self, *, result: AttachmentText, stage_version: str
    ) -> None:
        now = utcnow()
        values = {
            "blob_sha256": result.blob_sha256,
            "status": result.status.value,
            "text": result.text,
            "method": result.method,
            "page_count": result.page_count,
            "language": result.language,
            "error": result.error,
            "truncated": result.truncated,
            "text_sha256": result.text_sha256,
            "stage_version": stage_version,
            "created_at": now,
            "updated_at": now,
        }
        self._session.execute(
            pg_insert(models.AttachmentText)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[models.AttachmentText.blob_sha256],
                set_={
                    "status": values["status"],
                    "text": values["text"],
                    "method": values["method"],
                    "page_count": values["page_count"],
                    "language": values["language"],
                    "error": values["error"],
                    "truncated": values["truncated"],
                    "text_sha256": values["text_sha256"],
                    "stage_version": values["stage_version"],
                    "updated_at": now,
                },
            )
        )
