"""Account and account-identity persistence models.

``account`` is a Rosalind concept; ``account_identity`` maps an external
identity provider's ``(issuer, subject)`` onto an account. The split leaves
room for multiple identity providers (and multiple identities per account)
without leaking provider concepts into the account itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rosalind.adapters.outbound.persistence.models.base import Base, utcnow


class Account(Base):
    __tablename__ = "account"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    self_person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.person.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    identities: Mapped[list[AccountIdentity]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class AccountIdentity(Base):
    __tablename__ = "account_identity"
    __table_args__ = (
        UniqueConstraint(
            "issuer", "subject", name="uq_account_identity_issuer_subject"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    account: Mapped[Account] = relationship(back_populates="identities")
