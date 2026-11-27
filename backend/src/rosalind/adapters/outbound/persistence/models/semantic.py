"""Semantic-pipeline read/build models (``search`` schema).

These tables hold content-adjacent semantic state: sentence/clause segments,
sanitized overlay rows, coverage/verification bookkeeping, the job queue and
the spot-check queue. They are owned by the data backend's migration chain
(not the policy service), because they are derived from email and chunk text.

``derived.finding`` intentionally lives in ``derived.py`` next to the other
rebuildable derived data.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy.halfvec import HALFVEC
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from rosalind.adapters.outbound.persistence.models.base import Base, utcnow


class Segment(Base):
    __tablename__ = "segment"
    __table_args__ = (
        CheckConstraint(
            "field IN ('subject', 'body', 'quoted', 'attachment', 'attachment_name')",
            name="ck_segment_field",
        ),
        UniqueConstraint(
            "email_id",
            "field",
            "attachment_id",
            "ordinal",
            name="uq_segment_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("segment_email_idx", "email_id", "field"),
        Index("segment_chunk_idx", "chunk_id"),
        Index("segment_hash_idx", "text_hash"),
        Index(
            "segment_emb_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
        {"schema": "search"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"), nullable=False
    )
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.email_attachment.id", ondelete="CASCADE"), nullable=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("search.chunk.id", ondelete="CASCADE"), nullable=True
    )
    field: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_quoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    segmentation_version: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(1024), nullable=True)
    embedding_text_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class SemanticCoverage(Base):
    __tablename__ = "semantic_coverage"
    __table_args__ = ({"schema": "search"},)

    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search.segment.id", ondelete="CASCADE"), primary_key=True
    )
    statement_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    stage: Mapped[str] = mapped_column(Text, primary_key=True)
    classifier_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SemanticCandidate(Base):
    __tablename__ = "semantic_candidate"
    __table_args__ = ({"schema": "search"},)

    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search.segment.id", ondelete="CASCADE"), primary_key=True
    )
    statement_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class SemanticModelRun(Base):
    __tablename__ = "semantic_model_run"
    __table_args__ = (
        UniqueConstraint("classifier_version", name="uq_semantic_model_run_version"),
        {"schema": "search"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    quantization: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_version: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    window_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    classifier_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ChunkOverlay(Base):
    __tablename__ = "chunk_overlay"
    __table_args__ = (
        CheckConstraint(
            "status IN ('provisional', 'complete')", name="ck_chunk_overlay_status"
        ),
        Index("chunk_overlay_scope_time_idx", "source_account_num", "sent_at"),
        Index("chunk_overlay_sender_idx", "sender_handle"),
        Index(
            "chunk_overlay_participants_idx",
            "participant_handles",
            postgresql_using="gin",
        ),
        Index(
            "chunk_overlay_emb_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
        {"schema": "search"},
    )

    set_id: Mapped[str] = mapped_column(Text, primary_key=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search.chunk.id", ondelete="CASCADE"), primary_key=True
    )
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    index_text: Mapped[str] = mapped_column(Text, nullable=False)
    redactions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    findings_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(HALFVEC(1024), nullable=True)
    embedding_text_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Copies of the base row's access attributes so step-2 predicates apply
    # unchanged to overlay rows.
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.email_thread.id", ondelete="SET NULL"), nullable=True
    )
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
    from_handles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    to_handles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    cc_handles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    bcc_handles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    has_attachment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_trash_or_spam: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class FieldOverlay(Base):
    __tablename__ = "field_overlay"
    __table_args__ = (
        CheckConstraint(
            "status IN ('provisional', 'complete')", name="ck_field_overlay_status"
        ),
        UniqueConstraint(
            "set_id",
            "email_id",
            "field",
            "attachment_id",
            name="uq_field_overlay_key",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "search"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    set_id: Mapped[str] = mapped_column(Text, nullable=False)
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.email_message.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.email_attachment.id", ondelete="CASCADE"), nullable=True
    )
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    index_text: Mapped[str] = mapped_column(Text, nullable=False)
    redactions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    findings_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SemanticJob(Base):
    __tablename__ = "semantic_job"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'running', 'done', 'failed', 'paused')",
            name="ck_semantic_job_state",
        ),
        Index("semantic_job_pick_idx", "state", "priority", "run_after"),
        {"schema": "search"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    set_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SemanticReviewItem(Base):
    __tablename__ = "semantic_review_item"
    __table_args__ = (
        Index("semantic_review_item_open_idx", "resolved", "created_at"),
        {"schema": "search"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search.segment.id", ondelete="CASCADE"), nullable=False
    )
    statement_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class RedactionEvent(Base):
    __tablename__ = "redaction_event"
    __table_args__ = (
        Index("redaction_event_request_idx", "request_id"),
        Index("redaction_event_created_idx", "created_at"),
        {"schema": "search"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    statement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    segment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    segment_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    treatment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
