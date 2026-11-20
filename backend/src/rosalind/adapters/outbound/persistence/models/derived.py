"""Derived enrich-stage models (``derived`` schema).

Derived rows are rebuildable by definition: they are keyed by an input hash and
a stage version, replaced in place, and carry no provenance of their own. The
evidence they were computed from lives in ``core`` and ``raw``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from rosalind.adapters.outbound.persistence.models.base import Base, utcnow

_KINDS = ("new", "quoted", "forwarded", "signature", "disclaimer")

_EMAIL_TEXT_STATUS = ("done", "empty", "failed")

_ATTACHMENT_STATUS = (
    "done",
    "empty",
    "needs_ocr",
    "unsupported",
    "too_large",
    "encrypted",
    "failed",
)


class EmailText(Base):
    __tablename__ = "email_text"
    __table_args__ = (
        CheckConstraint(
            "status IN ('done', 'empty', 'failed')",
            name="ck_email_text_status",
        ),
        {"schema": "derived"},
    )

    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"), primary_key=True
    )
    clean_text: Mapped[str] = mapped_column(Text, nullable=False)
    clean_method: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    segments_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class EmailSegment(Base):
    __tablename__ = "email_segment"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('new', 'quoted', 'forwarded', 'signature', 'disclaimer')",
            name="ck_email_segment_kind",
        ),
        UniqueConstraint("email_id", "seq", name="uq_email_segment_email_seq"),
        {"schema": "derived"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attribution_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    quoted_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    quoted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    covered_by_email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="SET NULL"), nullable=True
    )
    coverage_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AttachmentText(Base):
    __tablename__ = "attachment_text"
    __table_args__ = (
        CheckConstraint(
            "status IN ('done', 'empty', 'needs_ocr', 'unsupported', 'too_large', "
            "'encrypted', 'failed')",
            name="ck_attachment_text_status",
        ),
        {"schema": "derived"},
    )

    blob_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    text_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class Finding(Base):
    """A verifier verdict linking a segment's text to a protected statement.

    Keyed by ``(text_hash, statement_id)`` so an identical sentence quoted
    elsewhere inherits the finding (positives propagate; negatives do not).
    ``segment_id`` is provenance for the segment that produced it. Spans are
    character offsets into the normalized segment text.
    """

    __tablename__ = "finding"
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('asserts', 'implies', 'evidence', 'none')",
            name="ck_finding_verdict",
        ),
        UniqueConstraint("text_hash", "statement_id", name="uq_finding_text_statement"),
        Index("finding_segment_idx", "segment_id"),
        {"schema": "derived"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search.segment.id", ondelete="CASCADE"), nullable=False
    )
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    statement_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    subject_matches: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    spans: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    classifier_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class FindingOverride(Base):
    """Owner spot-check correction for one ``(text_hash, statement_id)``.

    ``disabled`` suppresses the finding; otherwise the stored verdict overrides
    the model. Later verification runs respect it.
    """

    __tablename__ = "finding_override"
    __table_args__ = ({"schema": "derived"},)

    text_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    statement_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
