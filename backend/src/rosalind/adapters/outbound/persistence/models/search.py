"""Search chunk models (``search`` schema).

Chunks are the unit of retrieval: a passage of email body, quoted history, or
attachment text with a contextual prefix and denormalized filter columns. They
are rebuildable by definition — keyed deterministically and replaced in place
when their source digest or index version changes. ``chunk_build`` records the
build bookkeeping that drives the work finder.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from rosalind.adapters.outbound.persistence.models.base import Base, utcnow

_CHUNK_KINDS = ("email_body", "email_quote", "attachment")

_DIRECTIONS = ("received", "sent", "self", "unknown")

_BUILD_STATUS = ("done", "empty", "failed")


class Chunk(Base):
    __tablename__ = "chunk"
    __table_args__ = (
        CheckConstraint(
            "chunk_kind IN ('email_body', 'email_quote', 'attachment')",
            name="ck_chunk_kind",
        ),
        CheckConstraint(
            "direction IN ('received', 'sent', 'self', 'unknown')",
            name="ck_chunk_direction",
        ),
        UniqueConstraint(
            "email_id",
            "chunk_kind",
            "attachment_id",
            "seq",
            name="uq_chunk_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("chunk_scope_time_idx", "source_account_num", "sent_at"),
        Index("chunk_sender_idx", "sender_handle"),
        Index("chunk_thread_idx", "thread_id"),
        Index("chunk_email_idx", "email_id"),
        Index("chunk_recipients_idx", "recipient_handles", postgresql_using="gin"),
        Index("chunk_participants_idx", "participant_handles", postgresql_using="gin"),
        Index("chunk_tags_idx", "tags", postgresql_using="gin"),
        Index(
            "chunk_list_idx",
            "source_account_num",
            "sent_at",
            "email_id",
            postgresql_where=text("chunk_kind = 'email_body' AND seq = 0"),
        ),
        {"schema": "search"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"), nullable=False
    )
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.email_attachment.id", ondelete="CASCADE"), nullable=True
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.email_thread.id", ondelete="SET NULL"), nullable=True
    )
    chunk_kind: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    text_for_display: Mapped[str] = mapped_column(Text, nullable=False)
    text_for_index: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_version: Mapped[str] = mapped_column(Text, nullable=False)

    source_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_account_num: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sender_handle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recipient_handles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    participant_handles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    has_attachment: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_trash_or_spam: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ChunkBuild(Base):
    __tablename__ = "chunk_build"
    __table_args__ = (
        CheckConstraint(
            "status IN ('done', 'empty', 'failed')", name="ck_chunk_build_status"
        ),
        UniqueConstraint(
            "email_id",
            "chunk_kind",
            "attachment_id",
            name="uq_chunk_build_key",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "search"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"), nullable=False
    )
    chunk_kind: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.email_attachment.id", ondelete="CASCADE"), nullable=True
    )
    index_version: Mapped[str] = mapped_column(Text, nullable=False)
    source_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
