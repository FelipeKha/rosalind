"""Persistence for canonicalizing email messages.

The only module that talks SQL for the canonical email write path. ``save``
persists a whole ``CanonicalEmail`` aggregate atomically and owns the
version/observation idempotency checks: a record is skipped only when the
message already exists with matching parser/canonicalizer versions *and* its
observation has already been recorded; otherwise the children are replaced in
place.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.application.ports.repositories import EmailSaveResult
from rosalind.domain.email import CanonicalEmail

_STATUS_CREATED = "created"
_STATUS_UPDATED = "updated"
_STATUS_SKIPPED = "skipped"


class PostgresEmailCanonicalRepository:
    def __init__(self, session: Session):
        self._session = session

    def self_handles(self, account_id: uuid.UUID) -> set[str]:
        rows = self._session.scalars(
            select(models.PersonEmail.email_normalized)
            .join(
                models.Account,
                models.Account.self_person_id == models.PersonEmail.person_id,
            )
            .where(models.Account.id == account_id)
        ).all()
        return set(rows)

    def save(self, canonical: CanonicalEmail) -> EmailSaveResult:
        thread_id = self._upsert_thread(canonical)

        existing = self._session.scalar(
            select(models.EmailMessage).where(
                models.EmailMessage.source_account_id == canonical.source_account_id,
                models.EmailMessage.message_id == canonical.message_id,
            )
        )

        if existing is None:
            message = self._insert_message(canonical, thread_id)
            self._insert_observation(message.id, canonical)
            self._insert_children(message.id, canonical)
            return EmailSaveResult(message_id=message.id, status=_STATUS_CREATED)

        observation_new = self._insert_observation(existing.id, canonical)
        versions_match = (
            existing.parser_version == canonical.parser_version
            and existing.canonicalizer_version == canonical.canonicalizer_version
        )
        if not observation_new and versions_match:
            return EmailSaveResult(message_id=existing.id, status=_STATUS_SKIPPED)

        self._update_message(existing, canonical, thread_id)
        self._replace_children(existing.id, canonical)
        return EmailSaveResult(message_id=existing.id, status=_STATUS_UPDATED)

    def _upsert_thread(self, canonical: CanonicalEmail) -> uuid.UUID:
        values: dict[str, Any] = {
            "source_account_id": canonical.source_account_id,
            "root_message_id": canonical.thread.root_message_id,
            "provider_hint": canonical.thread.provider_hint,
        }
        inserted_id = self._session.scalar(
            pg_insert(models.EmailThread)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_email_thread_root")
            .returning(models.EmailThread.id)
        )
        if inserted_id is not None:
            return inserted_id
        thread_id = self._session.scalar(
            select(models.EmailThread.id).where(
                models.EmailThread.source_account_id == canonical.source_account_id,
                models.EmailThread.root_message_id == canonical.thread.root_message_id,
            )
        )
        if thread_id is None:
            raise RuntimeError("thread not found after upsert")
        return thread_id

    def _insert_message(
        self, canonical: CanonicalEmail, thread_id: uuid.UUID
    ) -> models.EmailMessage:
        message = models.EmailMessage(
            id=canonical.id,
            source_account_id=canonical.source_account_id,
            message_id=canonical.message_id,
            message_id_synthetic=canonical.message_id_synthetic,
            in_reply_to=canonical.in_reply_to,
            references=list(canonical.references) if canonical.references else None,
            occurred_at=canonical.occurred_at,
            utc_offset_minutes=canonical.utc_offset_minutes,
            direction=canonical.direction,
            subject=canonical.subject,
            text_plain=canonical.text_plain,
            text_html=canonical.text_html,
            has_attachments=canonical.has_attachments,
            is_trash_or_spam=canonical.is_trash_or_spam,
            thread_id=thread_id,
            parser_version=canonical.parser_version,
            canonicalizer_version=canonical.canonicalizer_version,
            metadata_=_metadata(canonical),
        )
        self._session.add(message)
        self._session.flush()
        return message

    def _update_message(
        self,
        message: models.EmailMessage,
        canonical: CanonicalEmail,
        thread_id: uuid.UUID,
    ) -> None:
        message.message_id_synthetic = canonical.message_id_synthetic
        message.in_reply_to = canonical.in_reply_to
        message.references = (
            list(canonical.references) if canonical.references else None
        )
        message.occurred_at = canonical.occurred_at
        message.utc_offset_minutes = canonical.utc_offset_minutes
        message.direction = canonical.direction
        message.subject = canonical.subject
        message.text_plain = canonical.text_plain
        message.text_html = canonical.text_html
        message.has_attachments = canonical.has_attachments
        message.is_trash_or_spam = canonical.is_trash_or_spam
        message.thread_id = thread_id
        message.parser_version = canonical.parser_version
        message.canonicalizer_version = canonical.canonicalizer_version
        message.metadata_ = _metadata(canonical)

    def _insert_observation(
        self, message_id: uuid.UUID, canonical: CanonicalEmail
    ) -> bool:
        inserted_id = self._session.scalar(
            pg_insert(models.EmailMessageObservation)
            .values(
                message_id=message_id,
                source_record_id=canonical.observation.source_record_id,
                observed_at=canonical.observation.observed_at,
            )
            .on_conflict_do_nothing(constraint="uq_email_message_observation_record")
            .returning(models.EmailMessageObservation.id)
        )
        return inserted_id is not None

    def _insert_children(
        self, message_id: uuid.UUID, canonical: CanonicalEmail
    ) -> None:
        for participant in canonical.participants:
            self._session.add(
                models.EmailParticipant(
                    message_id=message_id,
                    role=participant.role,
                    name=participant.name,
                    addr=participant.addr,
                    addr_normalized=participant.addr_normalized,
                    seq=participant.seq,
                )
            )
        for attachment in canonical.attachments:
            self._session.add(
                models.EmailAttachment(
                    message_id=message_id,
                    filename=attachment.filename,
                    declared_mime=attachment.declared_mime,
                    detected_mime=attachment.detected_mime,
                    size=attachment.size,
                    sha256=attachment.sha256,
                    disposition=attachment.disposition,
                    storage_key=attachment.storage_key,
                    part_index=attachment.part_index,
                    status="present",
                )
            )
        for tag in canonical.tags:
            self._session.add(models.EmailTag(message_id=message_id, tag=tag))

    def _replace_children(
        self, message_id: uuid.UUID, canonical: CanonicalEmail
    ) -> None:
        self._session.execute(
            delete(models.EmailParticipant).where(
                models.EmailParticipant.message_id == message_id
            )
        )
        self._session.execute(
            delete(models.EmailAttachment).where(
                models.EmailAttachment.message_id == message_id
            )
        )
        self._session.execute(
            delete(models.EmailTag).where(models.EmailTag.message_id == message_id)
        )
        self._insert_children(message_id, canonical)


def _metadata(canonical: CanonicalEmail) -> dict[str, Any]:
    warnings = [
        {"code": warning.code, "message": warning.message}
        for warning in canonical.parse_warnings
    ]
    return {"parse_warnings": warnings} if warnings else {}
