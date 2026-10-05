"""Canonical email models (``core`` schema).

One row per canonical message (``email_message``), with provenance kept in
``email_message_observation`` (a message can be observed by several raw
records when a later Takeout re-imports the same ``Message-ID`` with changed
labels). Participants, attachments, and tags are children of the message;
threads are a simple store keyed on the root message id (full reconciliation
is deferred).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from rosalind.adapters.outbound.persistence.models.base import Base, utcnow


class EmailMessage(Base):
    __tablename__ = "email_message"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('received', 'sent', 'self', 'unknown')",
            name="ck_email_message_direction",
        ),
        UniqueConstraint(
            "source_account_id", "message_id", name="uq_email_message_source_message"
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_account.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(Text, nullable=False)
    message_id_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    in_reply_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    references: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_plain: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_attachments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_trash_or_spam: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.email_thread.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    canonicalizer_version: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class EmailMessageObservation(Base):
    """Provenance: one raw record that produced (or re-produced) a message."""

    __tablename__ = "email_message_observation"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id", name="uq_email_message_observation_record"
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw.source_record.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class EmailThread(Base):
    __tablename__ = "email_thread"
    __table_args__ = (
        UniqueConstraint(
            "source_account_id", "root_message_id", name="uq_email_thread_root"
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_account.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    root_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_hint: Mapped[str | None] = mapped_column(Text, nullable=True)


class EmailParticipant(Base):
    __tablename__ = "email_participant"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "role",
            "addr_normalized",
            name="uq_email_participant_message_role_addr",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    addr: Mapped[str] = mapped_column(Text, nullable=False)
    addr_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EmailAttachment(Base):
    __tablename__ = "email_attachment"
    __table_args__ = (
        UniqueConstraint("message_id", "part_index", name="uq_email_attachment_part"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    declared_mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    disposition: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    part_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="present")


class EmailTag(Base):
    __tablename__ = "email_tag"
    __table_args__ = (
        UniqueConstraint("message_id", "tag", name="uq_email_tag_message_tag"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag: Mapped[str] = mapped_column(Text, nullable=False)
