"""Persistence for canonicalizing person observations.

The only module that talks SQL for the canonical person write path. Each
``upsert_*`` method records a fact, creates its ``source_assertion``, and links
the two, so the application layer never sees the fact/assertion/link tables.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.application.canonicalization.email import normalize_email
from rosalind.application.canonicalization.phone import normalize_phone
from rosalind.application.ports.repositories import FactUpsertResult, UnresolvedRelation
from rosalind.domain.person import (
    AddressObservation,
    DateObservation,
    EmailObservation,
    GenderObservation,
    ImObservation,
    LocaleObservation,
    NameObservation,
    NicknameObservation,
    NoteObservation,
    OrganizationObservation,
    PhoneObservation,
    RelationObservation,
    UrlObservation,
)
from rosalind.domain.source import SourceRef


class PostgresPersonCanonicalRepository:
    """Canonical-fact, provenance, and identity persistence for people."""

    def __init__(self, session: Session):
        self._session = session

    def find_person_ids(
        self, *, source_account_id: uuid.UUID, refs: tuple[SourceRef, ...]
    ) -> set[uuid.UUID]:
        person_ids: set[uuid.UUID] = set()
        for ref in refs:
            person_id = self._session.scalar(
                select(models.SourceIdentity.person_id).where(
                    models.SourceIdentity.source_account_id == source_account_id,
                    models.SourceIdentity.source_type == ref.source_type,
                    models.SourceIdentity.external_id == ref.external_id,
                )
            )
            if person_id is not None:
                person_ids.add(person_id)
        return person_ids

    def create_person(self) -> uuid.UUID:
        person = models.Person()
        self._session.add(person)
        self._session.flush()
        return person.id

    def upsert_source_identity(
        self,
        *,
        source_account_id: uuid.UUID,
        person_id: uuid.UUID,
        refs: tuple[SourceRef, ...],
        resource_name: str,
    ) -> dict[SourceRef, uuid.UUID]:
        identities: dict[SourceRef, uuid.UUID] = {}
        for ref in refs:
            values: dict[str, Any] = {
                "person_id": person_id,
                "source_account_id": source_account_id,
                "source_type": ref.source_type,
                "external_id": ref.external_id,
                "resource_name": resource_name,
            }
            identity_id, _ = self._upsert_returning(
                models.SourceIdentity,
                values,
                "uq_source_identity_account_type_external",
                select(models.SourceIdentity.id).where(
                    models.SourceIdentity.source_account_id == source_account_id,
                    models.SourceIdentity.source_type == ref.source_type,
                    models.SourceIdentity.external_id == ref.external_id,
                ),
            )
            identities[ref] = identity_id
        return identities

    def upsert_name(
        self,
        *,
        person_id: uuid.UUID,
        observation: NameObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonName,
            {
                "person_id": person_id,
                "display_name": observation.display_name,
                "given_name": observation.given_name,
                "family_name": observation.family_name,
                "middle_name": observation.middle_name,
                "name_prefix": observation.name_prefix,
                "name_suffix": observation.name_suffix,
                "previous_family_name": observation.previous_family_name,
                "phonetic_given_name": observation.phonetic_given_name,
                "phonetic_middle_name": observation.phonetic_middle_name,
                "phonetic_family_name": observation.phonetic_family_name,
                "phonetic_full_name": observation.phonetic_full_name,
                "is_primary": False,
            },
            "uq_person_name_value",
            select(models.PersonName.id).where(
                models.PersonName.person_id == person_id,
                models.PersonName.display_name == observation.display_name,
                models.PersonName.given_name == observation.given_name,
                models.PersonName.family_name == observation.family_name,
                models.PersonName.middle_name == observation.middle_name,
                models.PersonName.name_prefix == observation.name_prefix,
                models.PersonName.name_suffix == observation.name_suffix,
            ),
        )
        return self._finish(
            models.PersonNameAssertion,
            "person_name_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_email(
        self,
        *,
        person_id: uuid.UUID,
        observation: EmailObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        normalized = normalize_email(observation.value)
        fact_id, fact_created = self._upsert_returning(
            models.PersonEmail,
            {
                "person_id": person_id,
                "email": observation.value,
                "email_normalized": normalized,
                "type": observation.type,
                "is_primary": False,
                "is_verified": observation.source_verified is True,
            },
            "uq_person_email_person_normalized",
            select(models.PersonEmail.id).where(
                models.PersonEmail.person_id == person_id,
                models.PersonEmail.email_normalized == normalized,
            ),
        )
        return self._finish(
            models.PersonEmailAssertion,
            "person_email_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_date(
        self,
        *,
        person_id: uuid.UUID,
        observation: DateObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonDate,
            {
                "person_id": person_id,
                "date_type": observation.date_type,
                "year": observation.year,
                "month": observation.month,
                "day": observation.day,
                "is_primary": False,
            },
            "uq_person_date_value",
            select(models.PersonDate.id).where(
                models.PersonDate.person_id == person_id,
                models.PersonDate.date_type == observation.date_type,
                models.PersonDate.year == observation.year,
                models.PersonDate.month == observation.month,
                models.PersonDate.day == observation.day,
            ),
        )
        return self._finish(
            models.PersonDateAssertion,
            "person_date_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_gender(
        self,
        *,
        person_id: uuid.UUID,
        observation: GenderObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonGender,
            {"person_id": person_id, "value": observation.value, "is_primary": False},
            "uq_person_gender_value",
            select(models.PersonGender.id).where(
                models.PersonGender.person_id == person_id,
                models.PersonGender.value == observation.value,
            ),
        )
        return self._finish(
            models.PersonGenderAssertion,
            "person_gender_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_locale(
        self,
        *,
        person_id: uuid.UUID,
        observation: LocaleObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonLocale,
            {"person_id": person_id, "value": observation.value, "is_primary": False},
            "uq_person_locale_value",
            select(models.PersonLocale.id).where(
                models.PersonLocale.person_id == person_id,
                models.PersonLocale.value == observation.value,
            ),
        )
        return self._finish(
            models.PersonLocaleAssertion,
            "person_locale_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_phone(
        self,
        *,
        person_id: uuid.UUID,
        observation: PhoneObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        normalized = normalize_phone(observation.value)
        fact_id, fact_created = self._upsert_returning(
            models.PersonPhone,
            {
                "person_id": person_id,
                "value": observation.value,
                "value_normalized": normalized,
                "type": observation.type,
                "is_primary": False,
                "is_verified": observation.source_verified is True,
            },
            "uq_person_phone_person_normalized",
            select(models.PersonPhone.id).where(
                models.PersonPhone.person_id == person_id,
                models.PersonPhone.value_normalized == normalized,
            ),
        )
        return self._finish(
            models.PersonPhoneAssertion,
            "person_phone_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_address(
        self,
        *,
        person_id: uuid.UUID,
        observation: AddressObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonAddress,
            {
                "person_id": person_id,
                "type": observation.type,
                "formatted": observation.formatted,
                "street": observation.street,
                "city": observation.city,
                "region": observation.region,
                "postal_code": observation.postal_code,
                "country": observation.country,
                "country_code": observation.country_code,
                "is_primary": False,
            },
            "uq_person_address_value",
            select(models.PersonAddress.id).where(
                models.PersonAddress.person_id == person_id,
                models.PersonAddress.type == observation.type,
                models.PersonAddress.formatted == observation.formatted,
                models.PersonAddress.street == observation.street,
                models.PersonAddress.city == observation.city,
                models.PersonAddress.region == observation.region,
                models.PersonAddress.postal_code == observation.postal_code,
                models.PersonAddress.country == observation.country,
                models.PersonAddress.country_code == observation.country_code,
            ),
        )
        return self._finish(
            models.PersonAddressAssertion,
            "person_address_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_organization(
        self,
        *,
        person_id: uuid.UUID,
        observation: OrganizationObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonOrganization,
            {
                "person_id": person_id,
                "name": observation.name,
                "department": observation.department,
                "title": observation.title,
                "type": observation.type,
                "current": observation.current,
                "start_year": observation.start_year,
                "start_month": observation.start_month,
                "start_day": observation.start_day,
                "end_year": observation.end_year,
                "end_month": observation.end_month,
                "end_day": observation.end_day,
                "phonetic_name": observation.phonetic_name,
                "is_primary": False,
            },
            "uq_person_organization_value",
            select(models.PersonOrganization.id).where(
                models.PersonOrganization.person_id == person_id,
                models.PersonOrganization.name == observation.name,
                models.PersonOrganization.department == observation.department,
                models.PersonOrganization.title == observation.title,
                models.PersonOrganization.type == observation.type,
                models.PersonOrganization.start_year == observation.start_year,
                models.PersonOrganization.start_month == observation.start_month,
                models.PersonOrganization.start_day == observation.start_day,
            ),
        )
        return self._finish(
            models.PersonOrganizationAssertion,
            "person_organization_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_url(
        self,
        *,
        person_id: uuid.UUID,
        observation: UrlObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonUrl,
            {
                "person_id": person_id,
                "value": observation.value,
                "type": observation.type,
                "is_primary": False,
            },
            "uq_person_url_value",
            select(models.PersonUrl.id).where(
                models.PersonUrl.person_id == person_id,
                models.PersonUrl.value == observation.value,
            ),
        )
        return self._finish(
            models.PersonUrlAssertion,
            "person_url_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_im(
        self,
        *,
        person_id: uuid.UUID,
        observation: ImObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonIm,
            {
                "person_id": person_id,
                "service": observation.service,
                "username": observation.username,
                "type": observation.type,
                "is_primary": False,
            },
            "uq_person_im_value",
            select(models.PersonIm.id).where(
                models.PersonIm.person_id == person_id,
                models.PersonIm.service == observation.service,
                models.PersonIm.username == observation.username,
                models.PersonIm.type == observation.type,
            ),
        )
        return self._finish(
            models.PersonImAssertion,
            "person_im_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_note(
        self,
        *,
        person_id: uuid.UUID,
        observation: NoteObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonNote,
            {
                "person_id": person_id,
                "value": observation.value,
                "content_type": observation.content_type,
                "is_primary": False,
            },
            "uq_person_note_value",
            select(models.PersonNote.id).where(
                models.PersonNote.person_id == person_id,
                models.PersonNote.value == observation.value,
            ),
        )
        return self._finish(
            models.PersonNoteAssertion,
            "person_note_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_relation(
        self,
        *,
        person_id: uuid.UUID,
        observation: RelationObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonRelation,
            {
                "person_id": person_id,
                "type": observation.type,
                "related_person_name": observation.related_person_name,
                "related_person_id": None,
            },
            "uq_person_relation_value",
            select(models.PersonRelation.id).where(
                models.PersonRelation.person_id == person_id,
                models.PersonRelation.type == observation.type,
                models.PersonRelation.related_person_name
                == observation.related_person_name,
            ),
        )
        return self._finish(
            models.PersonRelationAssertion,
            "person_relation_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def upsert_nickname(
        self,
        *,
        person_id: uuid.UUID,
        observation: NicknameObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult:
        fact_id, fact_created = self._upsert_returning(
            models.PersonNickname,
            {
                "person_id": person_id,
                "value": observation.value,
                "type": observation.type,
                "is_primary": False,
            },
            "uq_person_nickname_value",
            select(models.PersonNickname.id).where(
                models.PersonNickname.person_id == person_id,
                models.PersonNickname.value == observation.value,
            ),
        )
        return self._finish(
            models.PersonNicknameAssertion,
            "person_nickname_id",
            fact_id,
            fact_created,
            source_record_id,
            source_identity_id,
            observation.field_path,
            observation.source_primary,
            observation.source_verified,
        )

    def set_name_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonName, person_id, fact_id)

    def set_email_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonEmail, person_id, fact_id)

    def set_date_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonDate, person_id, fact_id)

    def set_gender_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonGender, person_id, fact_id)

    def set_locale_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonLocale, person_id, fact_id)

    def set_phone_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonPhone, person_id, fact_id)

    def set_address_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonAddress, person_id, fact_id)

    def set_organization_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonOrganization, person_id, fact_id)

    def set_url_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonUrl, person_id, fact_id)

    def set_im_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonIm, person_id, fact_id)

    def set_note_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonNote, person_id, fact_id)

    def set_nickname_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None:
        self._set_primary(models.PersonNickname, person_id, fact_id)

    def list_unresolved_relations(self) -> list[UnresolvedRelation]:
        rows = self._session.execute(
            select(
                models.PersonRelation.id,
                models.PersonRelation.person_id,
                models.PersonRelation.related_person_name,
            ).where(models.PersonRelation.related_person_id.is_(None))
        ).all()
        return [
            UnresolvedRelation(
                relation_id=relation_id,
                person_id=person_id,
                related_person_name=related_person_name,
            )
            for relation_id, person_id, related_person_name in rows
            if related_person_name is not None
        ]

    def find_person_ids_by_name(self, *, normalized_name: str) -> set[uuid.UUID]:
        display_match = func.lower(func.btrim(models.PersonName.display_name))
        composed_match = func.lower(
            func.btrim(
                func.concat_ws(
                    " ", models.PersonName.given_name, models.PersonName.family_name
                )
            )
        )
        person_ids = self._session.scalars(
            select(models.PersonName.person_id).where(
                (display_match == normalized_name) | (composed_match == normalized_name)
            )
        ).all()
        return set(person_ids)

    def has_email(self, person_id: uuid.UUID) -> bool:
        return (
            self._session.scalar(
                select(models.PersonEmail.id)
                .where(models.PersonEmail.person_id == person_id)
                .limit(1)
            )
            is not None
        )

    def link_relation(
        self, *, relation_id: uuid.UUID, related_person_id: uuid.UUID
    ) -> None:
        self._session.execute(
            update(models.PersonRelation)
            .where(models.PersonRelation.id == relation_id)
            .values(related_person_id=related_person_id)
        )

    def _finish(
        self,
        link_entity: Any,
        fact_column: str,
        fact_id: uuid.UUID,
        fact_created: bool,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
        field_path: str,
        source_primary: bool | None,
        source_verified: bool | None,
    ) -> FactUpsertResult:
        assertion_id, assertion_created = self._upsert_returning(
            models.SourceAssertion,
            {
                "source_record_id": source_record_id,
                "source_identity_id": source_identity_id,
                "field_path": field_path,
                "source_primary": source_primary,
                "source_verified": source_verified,
                # ORM attribute for the JSONB "metadata" column is ``metadata_``.
                "metadata_": {},
            },
            "uq_source_assertion_record_field",
            select(models.SourceAssertion.id).where(
                models.SourceAssertion.source_record_id == source_record_id,
                models.SourceAssertion.field_path == field_path,
            ),
        )
        self._session.execute(
            pg_insert(link_entity)
            .values(**{"assertion_id": assertion_id, fact_column: fact_id})
            .on_conflict_do_nothing()
        )
        return FactUpsertResult(
            fact_id=fact_id,
            fact_created=fact_created,
            assertion_created=assertion_created,
        )

    def _upsert_returning(
        self,
        entity: Any,
        values: dict[str, Any],
        constraint: str,
        lookup: Any,
    ) -> tuple[uuid.UUID, bool]:
        """Insert with ``ON CONFLICT DO NOTHING``, returning the row id.

        Returns ``(id, created)`` where ``created`` is False when an existing row
        (found via ``lookup``) was reused.
        """
        inserted_id = self._session.scalar(
            pg_insert(entity)
            .values(**values)
            .on_conflict_do_nothing(constraint=constraint)
            .returning(entity.id)
        )
        if inserted_id is not None:
            return inserted_id, True

        existing_id = self._session.scalar(lookup)
        if existing_id is None:
            raise RuntimeError("row not found after upsert")
        return existing_id, False

    def _set_primary(
        self, entity: Any, person_id: uuid.UUID, selected_id: uuid.UUID | None
    ) -> None:
        self._session.execute(
            update(entity).where(entity.person_id == person_id).values(is_primary=False)
        )
        if selected_id is not None:
            self._session.execute(
                update(entity).where(entity.id == selected_id).values(is_primary=True)
            )
