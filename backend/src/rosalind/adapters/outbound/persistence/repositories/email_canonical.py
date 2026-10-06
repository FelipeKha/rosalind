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
from datetime import datetime
from typing import Any

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.models.base import utcnow
from rosalind.application.ports.repositories import (
    EmailSaveResult,
    ThreadReconcileResult,
)
from rosalind.domain.email import CanonicalEmail, ThreadEdge

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
            content_sha256=canonical.content_sha256,
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
        message.content_sha256 = canonical.content_sha256
        message.has_attachments = canonical.has_attachments
        message.is_trash_or_spam = canonical.is_trash_or_spam
        message.thread_id = thread_id
        message.parser_version = canonical.parser_version
        message.canonicalizer_version = canonical.canonicalizer_version
        message.metadata_ = _metadata(canonical)
        # Explicitly bump updated_at: a re-observation that only changes a child
        # (e.g. tags) leaves the message's own columns unchanged, so the ORM
        # onupdate would not fire. The chunk work finder relies on this bump to
        # refresh denormalized filter columns.
        message.updated_at = utcnow()

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

    def list_thread_edges(self, source_account_id: uuid.UUID) -> list[ThreadEdge]:
        rows = self._session.execute(
            select(
                models.EmailMessage.message_id,
                models.EmailMessage.in_reply_to,
                models.EmailMessage.references,
                models.EmailMessage.occurred_at,
            ).where(models.EmailMessage.source_account_id == source_account_id)
        ).all()
        return [
            ThreadEdge(
                message_id=message_id,
                in_reply_to=in_reply_to,
                references=tuple(references) if references else (),
                occurred_at=occurred_at,
            )
            for message_id, in_reply_to, references, occurred_at in rows
        ]

    def reconcile_threads(
        self, source_account_id: uuid.UUID, roots: dict[str, str]
    ) -> ThreadReconcileResult:
        """Apply computed thread roots, merging/splitting threads in place."""
        self._advisory_lock(source_account_id)

        message_rows = self._session.execute(
            select(
                models.EmailMessage.message_id,
                models.EmailMessage.thread_id,
            ).where(models.EmailMessage.source_account_id == source_account_id)
        ).all()
        current_thread = {
            message_id: thread_id for message_id, thread_id in message_rows
        }

        thread_rows = self._session.execute(
            select(
                models.EmailThread.id,
                models.EmailThread.root_message_id,
                models.EmailThread.created_at,
                func.count(models.EmailMessage.id),
            )
            .outerjoin(
                models.EmailMessage,
                models.EmailMessage.thread_id == models.EmailThread.id,
            )
            .where(models.EmailThread.source_account_id == source_account_id)
            .group_by(models.EmailThread.id)
        ).all()

        thread_root: dict[uuid.UUID, str] = {}
        thread_created: dict[uuid.UUID, datetime] = {}
        thread_count: dict[uuid.UUID, int] = {}
        for thread_id, root_message_id, created_at, count in thread_rows:
            thread_root[thread_id] = root_message_id
            thread_created[thread_id] = created_at
            thread_count[thread_id] = count

        groups: dict[str, list[str]] = {}
        for message_id in current_thread:
            root = roots.get(message_id)
            if root is None:
                continue
            groups.setdefault(root, []).append(message_id)

        thread_by_root = {root: tid for tid, root in thread_root.items()}
        group_roots = set(groups)
        preserved = {thread_by_root[r] for r in group_roots if r in thread_by_root}
        claimed = set(preserved)

        targets: dict[str, uuid.UUID] = {}
        renames: dict[uuid.UUID, str] = {}
        threads_created = 0

        for root in sorted(groups):
            members = groups[root]
            existing = thread_by_root.get(root)
            if existing is not None:
                targets[root] = existing
                continue
            candidates: set[uuid.UUID] = set()
            for message_id in members:
                member_thread = current_thread.get(message_id)
                if member_thread is not None:
                    candidates.add(member_thread)
            candidates -= claimed
            if candidates:
                best = max(
                    candidates,
                    key=lambda tid: (
                        thread_count.get(tid, 0),
                        -_epoch(thread_created.get(tid)),
                        -tid.int,
                    ),
                )
                targets[root] = best
                renames[best] = root
                claimed.add(best)
            else:
                targets[root] = self._create_thread(source_account_id, root)
                threads_created += 1

        messages_reassigned = 0
        changed_at = utcnow()
        for root, members in groups.items():
            target = targets[root]
            moved = [mid for mid in members if current_thread.get(mid) != target]
            if not moved:
                continue
            self._session.execute(
                update(models.EmailMessage)
                .where(
                    models.EmailMessage.source_account_id == source_account_id,
                    models.EmailMessage.message_id.in_(moved),
                )
                .values(thread_id=target, thread_changed_at=changed_at)
            )
            messages_reassigned += len(moved)

        # Delete now-empty threads first, so a later rename can't violate the
        # (source_account_id, root_message_id) unique constraint.
        empty_threads = self._session.scalars(
            select(models.EmailThread.id).where(
                models.EmailThread.source_account_id == source_account_id,
                ~exists(
                    select(models.EmailMessage.id).where(
                        models.EmailMessage.thread_id == models.EmailThread.id
                    )
                ),
            )
        ).all()
        for thread_id in empty_threads:
            self._session.execute(
                delete(models.EmailThread).where(models.EmailThread.id == thread_id)
            )
        threads_removed = len(empty_threads)

        for thread_id, root in renames.items():
            self._session.execute(
                update(models.EmailThread)
                .where(models.EmailThread.id == thread_id)
                .values(root_message_id=root)
            )

        return ThreadReconcileResult(
            threads_created=threads_created,
            threads_removed=threads_removed,
            messages_reassigned=messages_reassigned,
        )

    def _create_thread(self, source_account_id: uuid.UUID, root: str) -> uuid.UUID:
        thread = models.EmailThread(
            source_account_id=source_account_id,
            root_message_id=root,
            provider_hint=None,
        )
        self._session.add(thread)
        self._session.flush()
        return thread.id

    def _advisory_lock(self, source_account_id: uuid.UUID) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(source_account_id)},
        )


def _metadata(canonical: CanonicalEmail) -> dict[str, Any]:
    warnings = [
        {"code": warning.code, "message": warning.message}
        for warning in canonical.parse_warnings
    ]
    return {"parse_warnings": warnings} if warnings else {}


def _epoch(value: datetime | None) -> int:
    if value is None:
        return 0
    return int(value.timestamp())
