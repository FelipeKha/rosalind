"""Source account, credentials, and raw evidence models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rosalind.adapters.outbound.persistence.models.base import Base, utcnow


class SourceAccount(Base):
    __tablename__ = "source_account"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "account_identifier",
            name="uq_source_account_provider_identifier",
        ),
        UniqueConstraint("name", name="uq_source_account_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    credentials: Mapped[list[OAuthCredential]] = relationship(
        back_populates="source_account",
        cascade="all, delete-orphan",
    )


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    __table_args__ = (
        UniqueConstraint(
            "source_account_id",
            "provider",
            name="uq_oauth_credentials_account_provider",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    token_type: Mapped[str] = mapped_column(Text, nullable=False, default="Bearer")
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    source_account: Mapped[SourceAccount] = relationship(back_populates="credentials")


class OAuthAuthRequest(Base):
    __tablename__ = "oauth_auth_request"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    code_verifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SourceRecord(Base):
    """Immutable snapshot of a provider payload.

    Never cascade-deleted by downstream entity removal; this is the permanent
    audit trail from which canonical data can always be reconstructed.
    """

    __tablename__ = "source_record"
    __table_args__ = (
        UniqueConstraint(
            "source_account_id",
            "resource_type",
            "external_id",
            "payload_sha256",
            name="uq_source_record_snapshot",
        ),
        {"schema": "raw"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_account.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("imports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)
