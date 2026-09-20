"""Persistence models for import metadata."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Import(Base):
    __tablename__ = "imports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    file_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    import_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    files: Mapped[list[ImportFile]] = relationship(
        back_populates="import_",
        cascade="all, delete-orphan",
        order_by="ImportFile.path",
    )


class ImportFile(Base):
    __tablename__ = "import_files"
    __table_args__ = (
        UniqueConstraint("import_id", "path", name="uq_import_files_import_id_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)

    import_: Mapped[Import] = relationship(back_populates="files")


class SourceAccount(Base):
    __tablename__ = "source_account"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "account_identifier",
            name="uq_source_account_provider_identifier",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
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


# ==============================================================================
# Raw / evidence layer (immutable audit trail)
# ==============================================================================


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


# ==============================================================================
# Core / canonical layer
# ==============================================================================


class Person(Base):
    """Canonical person entity.

    Deliberately bare: attribute values live in their evidence tables
    (person_name, person_email, ...) and the current value is selected via
    is_primary, so a value is never duplicated between tables.
    """

    __tablename__ = "person"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SourceIdentity(Base):
    """Maps a person to an external identity, scoped to a source account.

    External IDs are never canonical: Google's resourceName can change, so the
    numeric source id is held in external_id and the full name in resource_name.
    """

    __tablename__ = "source_identity"
    __table_args__ = (
        UniqueConstraint(
            "source_account_id",
            "source_type",
            "external_id",
            name="uq_source_identity_account_type_external",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_account.id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    resource_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceAssertion(Base):
    """Field-level provenance for a single value within a source record.

    Survives person/fact deletion: an assertion is only removed together with
    its source_record, so the audit trail is preserved even after a canonical
    entity is deleted or merged.
    """

    __tablename__ = "source_assertion"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id", "field_path", name="uq_source_assertion_record_field"
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw.source_record.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.source_identity.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    field_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_primary: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class PersonName(Base):
    __tablename__ = "person_name"
    __table_args__ = (
        Index(
            "uq_person_name_one_primary",
            "person_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        UniqueConstraint(
            "person_id",
            "display_name",
            "given_name",
            "family_name",
            name="uq_person_name_value",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    given_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    family_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonEmail(Base):
    __tablename__ = "person_email"
    __table_args__ = (
        UniqueConstraint(
            "person_id", "email_normalized", name="uq_person_email_person_normalized"
        ),
        Index("ix_person_email_normalized", "email_normalized"),
        Index(
            "uq_person_email_one_primary",
            "person_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    email_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonDate(Base):
    """A whole or partial date (e.g. birthday) with no year/month/day duplication."""

    __tablename__ = "person_date"
    __table_args__ = (
        CheckConstraint(
            "month IS NULL OR (month BETWEEN 1 AND 12)", name="ck_person_date_month"
        ),
        CheckConstraint(
            "day IS NULL OR (day BETWEEN 1 AND 31)", name="ck_person_date_day"
        ),
        CheckConstraint(
            "day IS NULL OR month IS NOT NULL", name="ck_person_date_precision"
        ),
        Index(
            "uq_person_date_one_primary",
            "person_id",
            "date_type",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        UniqueConstraint(
            "person_id",
            "date_type",
            "year",
            "month",
            "day",
            name="uq_person_date_value",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date_type: Mapped[str] = mapped_column(Text, nullable=False, default="birthday")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonGender(Base):
    __tablename__ = "person_gender"
    __table_args__ = (
        Index(
            "uq_person_gender_one_primary",
            "person_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        UniqueConstraint("person_id", "value", name="uq_person_gender_value"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonLocale(Base):
    __tablename__ = "person_locale"
    __table_args__ = (
        Index(
            "uq_person_locale_one_primary",
            "person_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        UniqueConstraint("person_id", "value", name="uq_person_locale_value"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonNameAssertion(Base):
    """Links one canonical name to the assertions that support it."""

    __tablename__ = "person_name_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_name_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_name.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonEmailAssertion(Base):
    __tablename__ = "person_email_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_email.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonDateAssertion(Base):
    __tablename__ = "person_date_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_date_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_date.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonGenderAssertion(Base):
    __tablename__ = "person_gender_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_gender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_gender.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonLocaleAssertion(Base):
    __tablename__ = "person_locale_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_locale_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_locale.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
