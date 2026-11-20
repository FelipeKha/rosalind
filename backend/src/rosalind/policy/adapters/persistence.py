"""PostgreSQL persistence for the policy service.

Owns the ``authz``, ``semantic`` and ``audit`` schemas. It reads only the
directory/account tables it needs; it never reads email bodies or search
chunks.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from rosalind.adapters.outbound.persistence.models.account import (
    Account as AccountModel,
)
from rosalind.adapters.outbound.persistence.models.account import (
    AccountIdentity as AccountIdentityModel,
)
from rosalind.adapters.outbound.persistence.models.base import utcnow
from rosalind.adapters.outbound.persistence.models.email import (
    EmailMessage,
    EmailParticipant,
)
from rosalind.adapters.outbound.persistence.models.person import (
    PersonEmail,
    PersonName,
)
from rosalind.adapters.outbound.persistence.models.source import SourceAccount
from rosalind.policy.application.ports import (
    AccountRef,
    DraftRecord,
    NewPolicy,
    PersonCandidate,
    SourceAccountRef,
)
from rosalind.policy.domain.drafts import (
    PolicyDetail,
    PolicySource,
    PolicySummary,
)
from rosalind.security import decrypt_secret, encrypt_secret


class PolicyBase(DeclarativeBase):
    """Metadata for the tables the policy service owns.

    Cross-service FKs to ``account.id`` are declared in the Alembic migration,
    not here: ``account`` belongs to the data backend's metadata, and
    SQLAlchemy cannot resolve a ``ForeignKey`` across metadata objects during
    ORM flushes. The database still enforces the constraint.
    """


class PolicyModel(PolicyBase):
    __tablename__ = "policy"
    __table_args__ = (
        Index("ix_policy_account", "account_id"),
        {"schema": "authz"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    principal_kind: Mapped[str] = mapped_column(Text, nullable=False)
    policy_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class PolicyRevisionModel(PolicyBase):
    __tablename__ = "policy_revision"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "revision", name="uq_policy_revision_policy_revision"
        ),
        {"schema": "authz"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authz.policy.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    interpreter_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class PolicyBuildModel(PolicyBase):
    __tablename__ = "policy_build"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "revision", name="uq_policy_build_policy_revision"
        ),
        {"schema": "authz"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authz.policy.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classifier_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class PolicyDraftModel(PolicyBase):
    __tablename__ = "policy_draft"
    __table_args__ = (
        Index("ix_policy_draft_expires", "expires_at"),
        {"schema": "authz"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ProtectedStatementModel(PolicyBase):
    __tablename__ = "protected_statement"
    __table_args__ = (
        Index("ix_protected_statement_account", "account_id"),
        {"schema": "semantic"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    canonical_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class PolicyEventModel(PolicyBase):
    __tablename__ = "policy_event"
    __table_args__ = ({"schema": "audit"},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    principal_kind: Mapped[str] = mapped_column(Text, nullable=False)
    interpreter_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class PostgresPolicyRepository:
    """Policy repository backed by one SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    # ------------------------------------------------------------------ identity
    def get_or_create_account(self, issuer: str, subject: str) -> AccountRef:
        identity = self._session.scalar(
            select(AccountIdentityModel).where(
                AccountIdentityModel.issuer == issuer,
                AccountIdentityModel.subject == subject,
            )
        )
        account: AccountModel | None
        if identity is None:
            account = AccountModel()
            self._session.add(account)
            self._session.flush()
            identity = AccountIdentityModel(
                account_id=account.id, issuer=issuer, subject=subject
            )
            self._session.add(identity)
            self._session.flush()
        else:
            account = self._session.get(AccountModel, identity.account_id)
            if account is None:
                account = AccountModel(id=identity.account_id)
                self._session.add(account)
                self._session.flush()
        if account is None:
            raise RuntimeError("account provisioning failed")
        return AccountRef(id=account.id, self_person_id=account.self_person_id)

    def self_person_id(self, account_id: uuid.UUID) -> uuid.UUID | None:
        account = self._session.get(AccountModel, account_id)
        return account.self_person_id if account is not None else None

    # ----------------------------------------------------------------- directory
    def find_people(self, mention: str) -> list[PersonCandidate]:
        normalized = mention.strip().lower()
        if not normalized:
            return []

        person_ids: dict[uuid.UUID, str] = {}

        exact_names = self._session.execute(
            select(PersonName.person_id, PersonName.display_name).where(
                func.lower(PersonName.display_name) == normalized
            )
        ).all()
        for person_id, display_name in exact_names:
            person_ids[person_id] = display_name or mention.strip()

        if not person_ids:
            fuzzy_names = self._session.execute(
                select(PersonName.person_id, PersonName.display_name)
                .where(func.lower(PersonName.display_name).contains(normalized))
                .limit(10)
            ).all()
            for person_id, display_name in fuzzy_names:
                person_ids[person_id] = display_name or mention.strip()

        emails = self._session.execute(
            select(PersonEmail.person_id, PersonEmail.email).where(
                func.lower(PersonEmail.email_normalized) == normalized
            )
        ).all()
        for person_id, email in emails:
            person_ids.setdefault(person_id, email)

        candidates: list[PersonCandidate] = []
        for person_id, display_name in person_ids.items():
            addresses = list(
                self._session.scalars(
                    select(PersonEmail.email_normalized).where(
                        PersonEmail.person_id == person_id
                    )
                )
            )
            candidates.append(
                PersonCandidate(
                    person_id=person_id,
                    display_name=display_name,
                    addresses=sorted(set(addresses)),
                )
            )
        return sorted(candidates, key=lambda c: c.display_name.lower())

    def get_person(self, person_id: uuid.UUID) -> PersonCandidate | None:
        row = self._session.execute(
            select(PersonName.person_id, PersonName.display_name).where(
                PersonName.person_id == person_id
            )
        ).first()
        addresses = list(
            self._session.scalars(
                select(PersonEmail.email_normalized).where(
                    PersonEmail.person_id == person_id
                )
            )
        )
        if row is None and not addresses:
            return None
        display_name = (row[1] if row is not None else None) or (
            addresses[0] if addresses else str(person_id)
        )
        return PersonCandidate(
            person_id=person_id,
            display_name=display_name,
            addresses=sorted(set(addresses)),
        )

    def find_source_accounts(
        self, account_id: uuid.UUID, mention: str
    ) -> list[SourceAccountRef]:
        normalized = mention.strip().lower()
        if not normalized:
            return []
        rows = self._session.execute(
            select(SourceAccount.id, SourceAccount.name, SourceAccount.display_name)
            .where(SourceAccount.account_id == account_id)
            .where(
                (func.lower(SourceAccount.name) == normalized)
                | (func.lower(SourceAccount.display_name) == normalized)
            )
        ).all()
        return [
            SourceAccountRef(id=row[0], name=row[1] or "", display_name=row[2])
            for row in rows
        ]

    def get_source_account(
        self, account_id: uuid.UUID, source_account_id: uuid.UUID
    ) -> SourceAccountRef | None:
        row = self._session.execute(
            select(SourceAccount.id, SourceAccount.name, SourceAccount.display_name)
            .where(SourceAccount.account_id == account_id)
            .where(SourceAccount.id == source_account_id)
        ).first()
        if row is None:
            return None
        return SourceAccountRef(id=row[0], name=row[1] or "", display_name=row[2])

    def count_participant_emails(
        self, account_id: uuid.UUID, addresses: list[str]
    ) -> int:
        if not addresses:
            return 0
        value = self._session.scalar(
            select(func.count(func.distinct(EmailParticipant.message_id)))
            .join(EmailMessage, EmailMessage.id == EmailParticipant.message_id)
            .join(SourceAccount, SourceAccount.id == EmailMessage.source_account_id)
            .where(SourceAccount.account_id == account_id)
            .where(EmailParticipant.addr_normalized.in_(addresses))
        )
        return int(value or 0)

    # -------------------------------------------------------------------- drafts
    def create_draft(
        self, account_id: uuid.UUID, payload_encrypted: str, expires_at: datetime
    ) -> DraftRecord:
        model = PolicyDraftModel(
            account_id=account_id,
            payload_encrypted=payload_encrypted,
            expires_at=expires_at,
        )
        self._session.add(model)
        self._session.flush()
        return DraftRecord(
            draft_id=model.id,
            payload_encrypted=model.payload_encrypted,
            expires_at=model.expires_at,
        )

    def get_draft(
        self, account_id: uuid.UUID, draft_id: uuid.UUID
    ) -> DraftRecord | None:
        model = self._session.get(PolicyDraftModel, draft_id)
        if model is None or model.account_id != account_id:
            return None
        return DraftRecord(
            draft_id=model.id,
            payload_encrypted=model.payload_encrypted,
            expires_at=model.expires_at,
        )

    def update_draft(
        self,
        account_id: uuid.UUID,
        draft_id: uuid.UUID,
        payload_encrypted: str,
        expires_at: datetime,
    ) -> None:
        model = self._session.get(PolicyDraftModel, draft_id)
        if model is None or model.account_id != account_id:
            return
        model.payload_encrypted = payload_encrypted
        model.expires_at = expires_at
        self._session.flush()

    def delete_draft(self, account_id: uuid.UUID, draft_id: uuid.UUID) -> None:
        model = self._session.get(PolicyDraftModel, draft_id)
        if model is not None and model.account_id == account_id:
            self._session.delete(model)
            self._session.flush()

    def delete_expired_drafts(self, now: datetime) -> int:
        drafts = list(
            self._session.scalars(
                select(PolicyDraftModel).where(PolicyDraftModel.expires_at < now)
            )
        )
        for draft in drafts:
            self._session.delete(draft)
        self._session.flush()
        return len(drafts)

    # ------------------------------------------------------------------ policies
    def create_policy(self, policy: NewPolicy) -> PolicySummary:
        model = PolicyModel(
            account_id=policy.account_id,
            title=policy.title,
            principal_kind=policy.principal_kind,
            policy_type=policy.policy_type,
            status=policy.status,
            current_revision=1,
        )
        self._session.add(model)
        self._session.flush()

        revision = PolicyRevisionModel(
            policy_id=model.id,
            revision=1,
            spec=policy.spec,
            source_encrypted=encrypt_secret(policy.source.model_dump_json()),
            interpreter_version=policy.interpreter_version,
            model_id=policy.model_id,
        )
        self._session.add(revision)

        if policy.policy_type == "confidentiality":
            self._session.add(
                PolicyBuildModel(
                    policy_id=model.id,
                    revision=1,
                    status="pending_enforcement",
                )
            )
            if policy.statement is not None:
                self._session.add(
                    ProtectedStatementModel(
                        account_id=policy.account_id,
                        canonical_encrypted=encrypt_secret(policy.statement),
                        subject="self",
                        kind=policy.statement_kind or "fact",
                    )
                )

        self._session.add(
            PolicyEventModel(
                policy_id=model.id,
                revision=1,
                event="created",
                principal_kind=policy.principal_kind,
                interpreter_version=policy.interpreter_version,
                model_id=policy.model_id,
            )
        )
        self._session.flush()

        return PolicySummary(
            policy_id=model.id,
            revision=1,
            policy_type=policy.policy_type,  # type: ignore[arg-type]
            principal_kind=model.principal_kind,
            status=model.status,
            title=model.title,
        )

    def list_policies(self, account_id: uuid.UUID) -> list[PolicySummary]:
        policies = list(
            self._session.scalars(
                select(PolicyModel)
                .where(PolicyModel.account_id == account_id)
                .order_by(PolicyModel.created_at.desc())
            )
        )
        return [
            PolicySummary(
                policy_id=model.id,
                revision=model.current_revision,
                policy_type=model.policy_type,  # type: ignore[arg-type]
                principal_kind=model.principal_kind,
                status=model.status,
                title=model.title,
            )
            for model in policies
        ]

    def get_policy(
        self, account_id: uuid.UUID, policy_id: uuid.UUID
    ) -> PolicyDetail | None:
        model = self._session.get(PolicyModel, policy_id)
        if model is None or model.account_id != account_id:
            return None
        revision = self._session.scalar(
            select(PolicyRevisionModel).where(
                PolicyRevisionModel.policy_id == model.id,
                PolicyRevisionModel.revision == model.current_revision,
            )
        )
        if revision is None:
            return None
        source = PolicySource.model_validate_json(
            decrypt_secret(revision.source_encrypted)
        )
        return PolicyDetail(
            policy_id=model.id,
            revision=model.current_revision,
            policy_type=model.policy_type,
            principal_kind=model.principal_kind,
            status=model.status,
            spec=revision.spec,
            source=source,
            created_at=model.created_at,
        )

    def set_policy_status(
        self, account_id: uuid.UUID, policy_id: uuid.UUID, status: str
    ) -> PolicySummary | None:
        model = self._session.get(PolicyModel, policy_id)
        if model is None or model.account_id != account_id:
            return None
        model.status = status
        self._session.flush()
        return PolicySummary(
            policy_id=model.id,
            revision=model.current_revision,
            policy_type=model.policy_type,  # type: ignore[arg-type]
            principal_kind=model.principal_kind,
            status=model.status,
            title=model.title,
        )
