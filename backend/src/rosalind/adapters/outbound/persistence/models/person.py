"""Canonical person, identity, provenance, and fact models."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from rosalind.adapters.outbound.persistence.models.base import Base, utcnow


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
