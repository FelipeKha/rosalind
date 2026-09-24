"""Persistence for canonicalizing person observations.

The only module that talks SQL for the canonical person write path. Each
``upsert_*`` method records a fact, creates its ``source_assertion``, and links
the two, so the application layer never sees the fact/assertion/link tables.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.application.canonicalization.email import normalize_email
from rosalind.application.ports.repositories import FactUpsertResult
from rosalind.domain.person import (
    DateObservation,
    EmailObservation,
    GenderObservation,
    LocaleObservation,
    NameObservation,
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
                "is_primary": False,
            },
            "uq_person_name_value",
            select(models.PersonName.id).where(
                models.PersonName.person_id == person_id,
                models.PersonName.display_name == observation.display_name,
                models.PersonName.given_name == observation.given_name,
                models.PersonName.family_name == observation.family_name,
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
