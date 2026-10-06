"""Persistence for search chunks (``search.chunk`` / ``search.chunk_build``).

The only module that talks SQL for the chunk write path. ``list_stale_email_ids``
is the work finder; ``load_chunk_inputs`` assembles the full inputs for a batch
of emails; ``replace_chunks`` upserts drafts by deterministic id with an
only-if-changed guard, deletes chunks whose seq is past the new count, and
writes the build rows.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.models.base import utcnow
from rosalind.application.ports.search import (
    ChunkAttachmentInput,
    ChunkBuildRow,
    ChunkSegmentInput,
    ChunkWorkItem,
    ChunkWriteResult,
)
from rosalind.domain.search import ChunkDraft

_BODY_KINDS = ("email_body", "email_quote")
_ATTACHMENT_KIND = "attachment"

# Columns compared by the only-if-changed guard; a change to any of them counts
# as a rewrite (and later, in phase 6, nulls the embedding when text changed).
_MUTABLE_COLUMNS = [
    "text_for_display",
    "text_for_index",
    "text_sha256",
    "language",
    "index_version",
    "source_account_num",
    "sent_at",
    "sender_handle",
    "recipient_handles",
    "participant_handles",
    "direction",
    "has_attachment",
    "is_trash_or_spam",
    "tags",
    "thread_id",
    "meta",
]


class PostgresChunkRepository:
    def __init__(self, session: Session):
        self._session = session

    def list_stale_email_ids(
        self,
        *,
        source_account_id: uuid.UUID,
        index_version: str,
        limit: int,
    ) -> list[uuid.UUID]:
        m = models.EmailMessage
        t = models.EmailText
        bb = models.ChunkBuild

        # GREATEST returns NULL if any argument is NULL, so coalesce the nullable
        # thread_changed_at onto updated_at first.
        watermark = func.greatest(
            m.updated_at, func.coalesce(m.thread_changed_at, m.updated_at)
        )

        body_build = bb.__table__.alias("body_build")
        body_stale = or_(
            body_build.c.id.is_(None),
            body_build.c.index_version.is_distinct_from(index_version),
            body_build.c.source_digest.is_distinct_from(t.segments_digest),
            body_build.c.built_at < watermark,
        )
        body_candidate = and_(t.status.in_(_BODY_STATUS), body_stale)

        a = models.EmailAttachment
        at = models.AttachmentText
        att_build = bb.__table__.alias("att_build")
        attachment_digest = func.concat(at.stage_version, ":", at.text_sha256)
        attachment_stale = or_(
            att_build.c.id.is_(None),
            att_build.c.index_version.is_distinct_from(index_version),
            att_build.c.source_digest.is_distinct_from(attachment_digest),
            att_build.c.built_at < watermark,
        )
        attachment_candidate = (
            select(1)
            .select_from(a)
            .join(at, at.blob_sha256 == a.sha256)
            .outerjoin(
                att_build,
                and_(
                    att_build.c.email_id == a.message_id,
                    att_build.c.chunk_kind == _ATTACHMENT_KIND,
                    att_build.c.attachment_id == a.id,
                ),
            )
            .where(
                a.message_id == m.id,
                a.disposition != "inline",
                at.status == "done",
                attachment_stale,
            )
        )

        stmt = (
            select(m.id)
            .outerjoin(t, t.email_id == m.id)
            .outerjoin(
                body_build,
                and_(
                    body_build.c.email_id == m.id,
                    body_build.c.chunk_kind == _BODY_KINDS[0],
                    body_build.c.attachment_id.is_(None),
                ),
            )
            .where(
                m.source_account_id == source_account_id,
                or_(body_candidate, attachment_candidate.exists()),
            )
            .order_by(m.id)
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())

    def load_chunk_inputs(
        self, *, email_ids: Sequence[uuid.UUID]
    ) -> list[ChunkWorkItem]:
        if not email_ids:
            return []

        ids = list(email_ids)
        messages = self._load_messages(ids)
        participants = self._load_participants(ids)
        tags = self._load_tags(ids)
        texts = self._load_texts(ids)
        segments = self._load_segments(ids)
        attachments = self._load_attachments(ids)
        attachment_texts = self._load_attachment_texts(attachments)

        items: list[ChunkWorkItem] = []
        for message_id, msg in messages.items():
            parts = participants.get(message_id, [])
            sender_handle, sender_display = _sender(parts)
            recipient_handles, recipient_display = _recipients(parts)
            text = texts.get(message_id)

            attachments_for_message = []
            for att in attachments.get(message_id, []):
                at = attachment_texts.get(att.sha256)
                if at is None or not at.text_ready:
                    attachments_for_message.append(
                        ChunkAttachmentInput(
                            attachment_id=att.id,
                            filename=att.filename,
                            text=at.text if at else None,
                            truncated=at.truncated if at else False,
                            language=at.language if at else None,
                            stage_version=at.stage_version if at else None,
                            text_sha256=at.text_sha256 if at else None,
                            text_ready=False,
                        )
                    )
                else:
                    attachments_for_message.append(
                        ChunkAttachmentInput(
                            attachment_id=att.id,
                            filename=att.filename,
                            text=at.text,
                            truncated=at.truncated,
                            language=at.language,
                            stage_version=at.stage_version,
                            text_sha256=at.text_sha256,
                            text_ready=True,
                        )
                    )

            items.append(
                ChunkWorkItem(
                    email_id=message_id,
                    thread_id=msg.thread_id,
                    source_account_id=msg.source_account_id,
                    source_account_num=msg.source_account_num,
                    sent_at=msg.sent_at,
                    sender_handle=sender_handle,
                    sender_display=sender_display,
                    recipient_handles=tuple(sorted(recipient_handles)),
                    recipient_display=recipient_display,
                    participant_handles=tuple(
                        sorted({p.addr_normalized for p in parts})
                    ),
                    direction=msg.direction,
                    has_attachment=msg.has_attachments,
                    is_trash_or_spam=msg.is_trash_or_spam,
                    tags=tuple(sorted(tags.get(message_id, ()))),
                    subject=msg.subject,
                    clean_text=text.clean_text if text else None,
                    text_status=text.status if text else _MISSING_TEXT_STATUS,
                    segments_digest=text.segments_digest if text else None,
                    segments=segments.get(message_id, ()),
                    attachments=tuple(attachments_for_message),
                )
            )
        return items

    def replace_chunks(
        self,
        *,
        email_id: uuid.UUID,
        drafts: Sequence[ChunkDraft],
        builds: Sequence[ChunkBuildRow],
    ) -> ChunkWriteResult:
        drafts = list(drafts)

        # Remove chunks that are no longer produced (covered quotes, removed
        # attachments, shrunk seq). Draft ids are deterministic, so anything not
        # in the new set is stale.
        new_ids = [draft.id for draft in drafts]
        delete_stmt = delete(models.Chunk).where(models.Chunk.email_id == email_id)
        if new_ids:
            delete_stmt = delete_stmt.where(models.Chunk.id.not_in(new_ids))
        self._session.execute(delete_stmt)

        written = 0
        if drafts:
            insert = pg_insert(models.Chunk).values(
                [_draft_values(draft) for draft in drafts]
            )
            update_set = {
                name: getattr(insert.excluded, name) for name in _MUTABLE_COLUMNS
            }
            where = or_(
                *[
                    getattr(models.Chunk, name).is_distinct_from(
                        getattr(insert.excluded, name)
                    )
                    for name in _MUTABLE_COLUMNS
                ]
            )
            written = len(
                self._session.scalars(
                    insert.on_conflict_do_update(
                        index_elements=[models.Chunk.id],
                        set_=update_set,
                        where=where,
                    ).returning(models.Chunk.id)
                ).all()
            )

        # Rebuild the build rows entirely: they are small and complete per email.
        self._session.execute(
            delete(models.ChunkBuild).where(models.ChunkBuild.email_id == email_id)
        )
        for build in builds:
            self._session.add(
                models.ChunkBuild(
                    email_id=email_id,
                    chunk_kind=build.chunk_kind,
                    attachment_id=build.attachment_id,
                    index_version=build.index_version,
                    source_digest=build.source_digest,
                    built_at=build.built_at,
                    chunk_count=build.chunk_count,
                    status=build.status,
                    error=build.error,
                )
            )

        return ChunkWriteResult(written=written, unchanged=len(drafts) - written)

    # -- loaders ---------------------------------------------------------

    def _load_messages(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, _MessageRow]:
        rows = self._session.execute(
            select(
                models.EmailMessage.id,
                models.EmailMessage.thread_id,
                models.EmailMessage.source_account_id,
                models.SourceAccount.num,
                models.EmailMessage.occurred_at,
                models.EmailMessage.direction,
                models.EmailMessage.subject,
                models.EmailMessage.has_attachments,
                models.EmailMessage.is_trash_or_spam,
            )
            .join(
                models.SourceAccount,
                models.SourceAccount.id == models.EmailMessage.source_account_id,
            )
            .where(models.EmailMessage.id.in_(ids))
        ).all()
        return {
            message_id: _MessageRow(
                thread_id=thread_id,
                source_account_id=source_account_id,
                source_account_num=num,
                sent_at=occurred_at,
                direction=direction,
                subject=subject,
                has_attachments=has_attachments,
                is_trash_or_spam=is_trash_or_spam,
            )
            for (
                message_id,
                thread_id,
                source_account_id,
                num,
                occurred_at,
                direction,
                subject,
                has_attachments,
                is_trash_or_spam,
            ) in rows
        }

    def _load_participants(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
        rows = self._session.execute(
            select(
                models.EmailParticipant.message_id,
                models.EmailParticipant.role,
                models.EmailParticipant.name,
                models.EmailParticipant.addr,
                models.EmailParticipant.addr_normalized,
                models.EmailParticipant.seq,
            )
            .where(models.EmailParticipant.message_id.in_(ids))
            .order_by(
                models.EmailParticipant.message_id,
                models.EmailParticipant.seq,
            )
        ).all()
        grouped: dict[uuid.UUID, list] = defaultdict(list)
        for message_id, role, name, addr, addr_normalized, seq in rows:
            grouped[message_id].append(
                _ParticipantRow(role, name, addr, addr_normalized, seq)
            )
        return grouped

    def _load_tags(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, ...]]:
        rows = self._session.execute(
            select(models.EmailTag.message_id, models.EmailTag.tag).where(
                models.EmailTag.message_id.in_(ids)
            )
        ).all()
        grouped: dict[uuid.UUID, list[str]] = defaultdict(list)
        for message_id, tag in rows:
            grouped[message_id].append(tag)
        return {k: tuple(v) for k, v in grouped.items()}

    def _load_texts(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, _TextRow]:
        rows = self._session.execute(
            select(
                models.EmailText.email_id,
                models.EmailText.clean_text,
                models.EmailText.status,
                models.EmailText.segments_digest,
            ).where(models.EmailText.email_id.in_(ids))
        ).all()
        return {
            email_id: _TextRow(clean_text, status, segments_digest)
            for email_id, clean_text, status, segments_digest in rows
        }

    def _load_segments(
        self, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[ChunkSegmentInput, ...]]:
        rows = self._session.execute(
            select(
                models.EmailSegment.email_id,
                models.EmailSegment.kind,
                models.EmailSegment.start_offset,
                models.EmailSegment.end_offset,
                models.EmailSegment.language,
                models.EmailSegment.covered_by_email_id,
                models.EmailSegment.quoted_author,
            )
            .where(models.EmailSegment.email_id.in_(ids))
            .order_by(models.EmailSegment.email_id, models.EmailSegment.seq)
        ).all()
        grouped: dict[uuid.UUID, list[ChunkSegmentInput]] = defaultdict(list)
        for email_id, kind, start, end, language, covered, quoted_author in rows:
            grouped[email_id].append(
                ChunkSegmentInput(kind, start, end, language, covered, quoted_author)
            )
        return {k: tuple(v) for k, v in grouped.items()}

    def _load_attachments(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
        rows = self._session.execute(
            select(
                models.EmailAttachment.message_id,
                models.EmailAttachment.id,
                models.EmailAttachment.filename,
                models.EmailAttachment.sha256,
            )
            .where(
                models.EmailAttachment.message_id.in_(ids),
                models.EmailAttachment.disposition != "inline",
            )
            .order_by(models.EmailAttachment.part_index)
        ).all()
        grouped: dict[uuid.UUID, list] = defaultdict(list)
        for message_id, attachment_id, filename, sha256 in rows:
            grouped[message_id].append(_AttachmentRow(attachment_id, filename, sha256))
        return grouped

    def _load_attachment_texts(
        self, attachments: dict[uuid.UUID, list]
    ) -> dict[str, _AttachmentTextRow]:
        hashes = {att.sha256 for atts in attachments.values() for att in atts}
        if not hashes:
            return {}
        rows = self._session.execute(
            select(
                models.AttachmentText.blob_sha256,
                models.AttachmentText.status,
                models.AttachmentText.text,
                models.AttachmentText.truncated,
                models.AttachmentText.language,
                models.AttachmentText.stage_version,
                models.AttachmentText.text_sha256,
            ).where(models.AttachmentText.blob_sha256.in_(hashes))
        ).all()
        return {
            sha256: _AttachmentTextRow(
                status, text, truncated, language, stage_version, text_sha256
            )
            for sha256, status, text, truncated, language, stage_version, text_sha256 in rows
        }


# -- row helpers ----------------------------------------------------------


@dataclass(frozen=True)
class _MessageRow:
    thread_id: uuid.UUID | None
    source_account_id: uuid.UUID
    source_account_num: int
    sent_at: datetime
    direction: str
    subject: str | None
    has_attachments: bool
    is_trash_or_spam: bool


@dataclass(frozen=True)
class _ParticipantRow:
    role: str
    name: str | None
    addr: str
    addr_normalized: str
    seq: int


@dataclass(frozen=True)
class _TextRow:
    clean_text: str
    status: str
    segments_digest: str | None


@dataclass(frozen=True)
class _AttachmentRow:
    id: uuid.UUID
    filename: str | None
    sha256: str


@dataclass(frozen=True)
class _AttachmentTextRow:
    status: str
    text: str | None
    truncated: bool
    language: str | None
    stage_version: str | None
    text_sha256: str | None

    @property
    def text_ready(self) -> bool:
        return self.status == "done"


# Body/quote sources are ready when the derived text exists and is not failed.
_BODY_STATUS = ("done", "empty")
_MISSING_TEXT_STATUS = "missing"


def _sender(participants: list[_ParticipantRow]) -> tuple[str, str]:
    from_rows = sorted(
        (p for p in participants if p.role == "from"), key=lambda p: p.seq
    )
    if not from_rows:
        return "", ""
    sender = from_rows[0]
    return sender.addr_normalized, _display(sender.name, sender.addr)


def _recipients(
    participants: list[_ParticipantRow],
) -> tuple[list[str], tuple[str, ...]]:
    recipients = sorted(
        (p for p in participants if p.role in ("to", "cc", "bcc")),
        key=lambda p: p.seq,
    )
    handles = [p.addr_normalized for p in recipients]
    display = tuple(_display(p.name, p.addr) for p in recipients)
    return handles, display


def _display(name: str | None, addr: str) -> str:
    if name:
        return f"{name} <{addr}>"
    return addr


def _draft_values(draft: ChunkDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "email_id": draft.email_id,
        "attachment_id": draft.attachment_id,
        "thread_id": draft.thread_id,
        "chunk_kind": draft.kind.value,
        "seq": draft.seq,
        "text_for_display": draft.text_for_display,
        "text_for_index": draft.text_for_index,
        "text_sha256": draft.text_sha256,
        "language": draft.language,
        "index_version": draft.index_version,
        "source_account_id": draft.source_account_id,
        "source_account_num": draft.source_account_num,
        "sent_at": draft.sent_at,
        "sender_handle": draft.sender_handle,
        "recipient_handles": list(draft.recipient_handles),
        "participant_handles": list(draft.participant_handles),
        "direction": draft.direction,
        "has_attachment": draft.has_attachment,
        "is_trash_or_spam": draft.is_trash_or_spam,
        "tags": list(draft.tags),
        "meta": draft.meta,
        "created_at": utcnow(),
    }
