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
            "middle_name",
            "name_prefix",
            "name_suffix",
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
    middle_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_suffix: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_family_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phonetic_given_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phonetic_middle_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phonetic_family_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phonetic_full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class PersonPhone(Base):
    __tablename__ = "person_phone"
    __table_args__ = (
        UniqueConstraint(
            "person_id", "value_normalized", name="uq_person_phone_person_normalized"
        ),
        Index(
            "uq_person_phone_one_primary",
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
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonAddress(Base):
    __tablename__ = "person_address"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "type",
            "formatted",
            "street",
            "city",
            "region",
            "postal_code",
            "country",
            "country_code",
            name="uq_person_address_value",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_person_address_one_primary",
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
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    formatted: Mapped[str | None] = mapped_column(Text, nullable=True)
    street: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    postal_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonOrganization(Base):
    """A past or current organization, with optional partial date ranges."""

    __tablename__ = "person_organization"
    __table_args__ = (
        CheckConstraint(
            "start_month IS NULL OR (start_month BETWEEN 1 AND 12)",
            name="ck_person_organization_start_month",
        ),
        CheckConstraint(
            "end_month IS NULL OR (end_month BETWEEN 1 AND 12)",
            name="ck_person_organization_end_month",
        ),
        CheckConstraint(
            "start_day IS NULL OR start_month IS NOT NULL",
            name="ck_person_organization_start_precision",
        ),
        CheckConstraint(
            "end_day IS NULL OR end_month IS NOT NULL",
            name="ck_person_organization_end_precision",
        ),
        UniqueConstraint(
            "person_id",
            "name",
            "department",
            "title",
            "type",
            "start_year",
            "start_month",
            "start_day",
            name="uq_person_organization_value",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_person_organization_one_primary",
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
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    current: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    start_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phonetic_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonUrl(Base):
    __tablename__ = "person_url"
    __table_args__ = (
        UniqueConstraint("person_id", "value", name="uq_person_url_value"),
        Index(
            "uq_person_url_one_primary",
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
    value: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonIm(Base):
    __tablename__ = "person_im"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "service",
            "username",
            "type",
            name="uq_person_im_value",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_person_im_one_primary",
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
    service: Mapped[str | None] = mapped_column(Text, nullable=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonNote(Base):
    __tablename__ = "person_note"
    __table_args__ = (
        UniqueConstraint("person_id", "value", name="uq_person_note_value"),
        Index(
            "uq_person_note_one_primary",
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
    value: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PersonRelation(Base):
    """A directed edge from a person to another person (or an unresolved name).

    ``type`` describes what ``related_person`` is to ``person_id`` (e.g. a
    ``spouse`` relation on A pointing at B means "B is A's spouse"). The target
    is resolved by a later pass: initially only ``related_person_name`` is set,
    and ``related_person_id`` is filled once an unambiguous person is matched.
    """

    __tablename__ = "person_relation"
    __table_args__ = (
        CheckConstraint(
            "related_person_id IS NOT NULL OR related_person_name IS NOT NULL",
            name="ck_person_relation_target",
        ),
        UniqueConstraint(
            "person_id",
            "type",
            "related_person_name",
            name="uq_person_relation_value",
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person.id", ondelete="CASCADE"), nullable=False, index=True
    )
    related_person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.person.id", ondelete="SET NULL"), nullable=True, index=True
    )
    related_person_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)


class PersonNickname(Base):
    __tablename__ = "person_nickname"
    __table_args__ = (
        UniqueConstraint("person_id", "value", name="uq_person_nickname_value"),
        Index(
            "uq_person_nickname_one_primary",
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
    value: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class PersonPhoneAssertion(Base):
    __tablename__ = "person_phone_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_phone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_phone.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonAddressAssertion(Base):
    __tablename__ = "person_address_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_address_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_address.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonOrganizationAssertion(Base):
    __tablename__ = "person_organization_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_organization.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonUrlAssertion(Base):
    __tablename__ = "person_url_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_url_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_url.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonImAssertion(Base):
    __tablename__ = "person_im_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_im_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_im.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonNoteAssertion(Base):
    __tablename__ = "person_note_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_note.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonRelationAssertion(Base):
    __tablename__ = "person_relation_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_relation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_relation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class PersonNicknameAssertion(Base):
    __tablename__ = "person_nickname_assertion"
    __table_args__ = {"schema": "core"}  # noqa: RUF012

    assertion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.source_assertion.id", ondelete="CASCADE"), primary_key=True
    )
    person_nickname_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.person_nickname.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
