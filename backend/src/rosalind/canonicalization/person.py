"""Canonicalize a person observation into the ``core`` schema.

Idempotency is database-driven: PostgreSQL uniqueness constraints plus
``INSERT ... ON CONFLICT`` guard every fact and assertion, so re-processing the
same source record (or an identical payload) never creates duplicates.

Primary selection treats ``source_primary`` as an input signal, not an
invariant: it is Rosalind that decides ``is_primary``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind import models
from rosalind.canonicalization.email import normalize_email
from rosalind.domain.observations.person import (
    DateObservation,
    EmailObservation,
    GenderObservation,
    LocaleObservation,
    NameObservation,
    PersonObservation,
    SourceRef,
)
from rosalind.ingestion.errors import EntityResolutionConflictError


@dataclass(frozen=True)
class CanonicalizationResult:
    person_id: uuid.UUID
    created: bool
    facts_created: int
    facts_reused: int
    assertions_created: int


def canonicalize(
    db: Session,
    source_account: models.SourceAccount,
    source_record: models.SourceRecord,
    observation: PersonObservation,
) -> CanonicalizationResult:
    """Persist canonical facts and provenance for one source record.

    Runs within the caller's transaction; flushes but does not commit.
    """
    person_id, created = _resolve_or_create_person(
        db, source_account, observation.source_identities
    )
    identities = _upsert_source_identities(
        db, source_account, source_record, person_id, observation.source_identities
    )

    counters = {"facts_created": 0, "facts_reused": 0, "assertions_created": 0}

    name_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
    for name_obs in observation.names:
        fact_id = _apply_name(
            db, person_id, name_obs, source_record, identities, counters
        )
        name_candidates.append(
            (fact_id, name_obs.source_primary, _name_sort_key(name_obs))
        )

    email_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
    for email_obs in observation.emails:
        fact_id = _apply_email(
            db, person_id, email_obs, source_record, identities, counters
        )
        email_candidates.append(
            (fact_id, email_obs.source_primary, normalize_email(email_obs.value))
        )

    date_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
    for date_obs in observation.dates:
        fact_id = _apply_date(
            db, person_id, date_obs, source_record, identities, counters
        )
        date_candidates.append(
            (fact_id, date_obs.source_primary, _date_sort_key(date_obs))
        )

    gender_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
    for gender_obs in observation.genders:
        fact_id = _apply_gender(
            db, person_id, gender_obs, source_record, identities, counters
        )
        gender_candidates.append((fact_id, gender_obs.source_primary, gender_obs.value))

    locale_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
    for locale_obs in observation.locales:
        fact_id = _apply_locale(
            db, person_id, locale_obs, source_record, identities, counters
        )
        locale_candidates.append((fact_id, locale_obs.source_primary, locale_obs.value))

    _set_primary(db, models.PersonName, person_id, _select_primary(name_candidates))
    _set_primary(db, models.PersonEmail, person_id, _select_primary(email_candidates))
    _set_primary(db, models.PersonDate, person_id, _select_primary(date_candidates))
    _set_primary(db, models.PersonGender, person_id, _select_primary(gender_candidates))
    _set_primary(db, models.PersonLocale, person_id, _select_primary(locale_candidates))

    db.flush()
    return CanonicalizationResult(
        person_id=person_id,
        created=created,
        facts_created=counters["facts_created"],
        facts_reused=counters["facts_reused"],
        assertions_created=counters["assertions_created"],
    )


def _resolve_or_create_person(
    db: Session, source_account: models.SourceAccount, refs: tuple[SourceRef, ...]
) -> tuple[uuid.UUID, bool]:
    person_ids: set[uuid.UUID] = set()
    for ref in refs:
        person_id = db.scalar(
            select(models.SourceIdentity.person_id).where(
                models.SourceIdentity.source_account_id == source_account.id,
                models.SourceIdentity.source_type == ref.source_type,
                models.SourceIdentity.external_id == ref.external_id,
            )
        )
        if person_id is not None:
            person_ids.add(person_id)

    if len(person_ids) > 1:
        raise EntityResolutionConflictError(
            "source identities resolve to multiple persons: "
            f"{sorted(str(p) for p in person_ids)}"
        )
    if len(person_ids) == 1:
        return person_ids.pop(), False

    person = models.Person()
    db.add(person)
    db.flush()
    return person.id, True


def _upsert_source_identities(
    db: Session,
    source_account: models.SourceAccount,
    source_record: models.SourceRecord,
    person_id: uuid.UUID,
    refs: tuple[SourceRef, ...],
) -> dict[tuple[str, str], uuid.UUID]:
    identities: dict[tuple[str, str], uuid.UUID] = {}
    for ref in refs:
        values: dict[str, Any] = {
            "person_id": person_id,
            "source_account_id": source_account.id,
            "source_type": ref.source_type,
            "external_id": ref.external_id,
            "resource_name": source_record.external_id,
        }
        identity_id, _ = _upsert_returning(
            db,
            models.SourceIdentity,
            values,
            "uq_source_identity_account_type_external",
            select(models.SourceIdentity.id).where(
                models.SourceIdentity.source_account_id == source_account.id,
                models.SourceIdentity.source_type == ref.source_type,
                models.SourceIdentity.external_id == ref.external_id,
            ),
        )
        identities[(ref.source_type, ref.external_id)] = identity_id
    return identities


def _create_assertion(
    db: Session,
    source_record: models.SourceRecord,
    field_path: str,
    source: SourceRef | None,
    source_primary: bool | None,
    source_verified: bool | None,
    identities: dict[tuple[str, str], uuid.UUID],
    counters: dict[str, int],
) -> uuid.UUID:
    source_identity_id = (
        identities.get((source.source_type, source.external_id)) if source else None
    )
    values: dict[str, Any] = {
        "source_record_id": source_record.id,
        "source_identity_id": source_identity_id,
        "field_path": field_path,
        "source_primary": source_primary,
        "source_verified": source_verified,
        # ORM attribute for the JSONB "metadata" column is ``metadata_``.
        "metadata_": {},
    }
    assertion_id, created = _upsert_returning(
        db,
        models.SourceAssertion,
        values,
        "uq_source_assertion_record_field",
        select(models.SourceAssertion.id).where(
            models.SourceAssertion.source_record_id == source_record.id,
            models.SourceAssertion.field_path == field_path,
        ),
    )
    if created:
        counters["assertions_created"] += 1
    return assertion_id


def _upsert_returning(
    db: Session,
    entity: Any,
    values: dict[str, Any],
    constraint: str,
    lookup: Any,
) -> tuple[uuid.UUID, bool]:
    """Insert with ``ON CONFLICT DO NOTHING``, returning the id of the row.

    Returns ``(id, created)`` where ``created`` is False when an existing row
    (found via ``lookup``) was reused.
    """
    inserted_id = db.scalar(
        pg_insert(entity)
        .values(**values)
        .on_conflict_do_nothing(constraint=constraint)
        .returning(entity.id)
    )
    if inserted_id is not None:
        return inserted_id, True

    existing_id = db.scalar(lookup)
    if existing_id is None:
        raise RuntimeError("row not found after upsert")
    return existing_id, False


def _link_assertion(
    db: Session,
    link_entity: Any,
    assertion_id: uuid.UUID,
    fact_id: uuid.UUID,
    fact_column: str,
) -> None:
    db.execute(
        pg_insert(link_entity)
        .values(**{"assertion_id": assertion_id, fact_column: fact_id})
        .on_conflict_do_nothing()
    )


def _apply_name(
    db: Session,
    person_id: uuid.UUID,
    obs: NameObservation,
    source_record: models.SourceRecord,
    identities: dict[tuple[str, str], uuid.UUID],
    counters: dict[str, int],
) -> uuid.UUID:
    fact_id, created = _upsert_returning(
        db,
        models.PersonName,
        {
            "person_id": person_id,
            "display_name": obs.display_name,
            "given_name": obs.given_name,
            "family_name": obs.family_name,
            "is_primary": False,
        },
        "uq_person_name_value",
        select(models.PersonName.id).where(
            models.PersonName.person_id == person_id,
            models.PersonName.display_name == obs.display_name,
            models.PersonName.given_name == obs.given_name,
            models.PersonName.family_name == obs.family_name,
        ),
    )
    _count_fact(counters, created)
    assertion_id = _create_assertion(
        db,
        source_record,
        obs.field_path,
        obs.source,
        obs.source_primary,
        obs.source_verified,
        identities,
        counters,
    )
    _link_assertion(
        db, models.PersonNameAssertion, assertion_id, fact_id, "person_name_id"
    )
    return fact_id


def _apply_email(
    db: Session,
    person_id: uuid.UUID,
    obs: EmailObservation,
    source_record: models.SourceRecord,
    identities: dict[tuple[str, str], uuid.UUID],
    counters: dict[str, int],
) -> uuid.UUID:
    normalized = normalize_email(obs.value)
    fact_id, created = _upsert_returning(
        db,
        models.PersonEmail,
        {
            "person_id": person_id,
            "email": obs.value,
            "email_normalized": normalized,
            "type": obs.type,
            "is_primary": False,
            "is_verified": obs.source_verified is True,
        },
        "uq_person_email_person_normalized",
        select(models.PersonEmail.id).where(
            models.PersonEmail.person_id == person_id,
            models.PersonEmail.email_normalized == normalized,
        ),
    )
    _count_fact(counters, created)
    assertion_id = _create_assertion(
        db,
        source_record,
        obs.field_path,
        obs.source,
        obs.source_primary,
        obs.source_verified,
        identities,
        counters,
    )
    _link_assertion(
        db, models.PersonEmailAssertion, assertion_id, fact_id, "person_email_id"
    )
    return fact_id


def _apply_date(
    db: Session,
    person_id: uuid.UUID,
    obs: DateObservation,
    source_record: models.SourceRecord,
    identities: dict[tuple[str, str], uuid.UUID],
    counters: dict[str, int],
) -> uuid.UUID:
    fact_id, created = _upsert_returning(
        db,
        models.PersonDate,
        {
            "person_id": person_id,
            "date_type": obs.date_type,
            "year": obs.year,
            "month": obs.month,
            "day": obs.day,
            "is_primary": False,
        },
        "uq_person_date_value",
        select(models.PersonDate.id).where(
            models.PersonDate.person_id == person_id,
            models.PersonDate.date_type == obs.date_type,
            models.PersonDate.year == obs.year,
            models.PersonDate.month == obs.month,
            models.PersonDate.day == obs.day,
        ),
    )
    _count_fact(counters, created)
    assertion_id = _create_assertion(
        db,
        source_record,
        obs.field_path,
        obs.source,
        obs.source_primary,
        obs.source_verified,
        identities,
        counters,
    )
    _link_assertion(
        db, models.PersonDateAssertion, assertion_id, fact_id, "person_date_id"
    )
    return fact_id


def _apply_gender(
    db: Session,
    person_id: uuid.UUID,
    obs: GenderObservation,
    source_record: models.SourceRecord,
    identities: dict[tuple[str, str], uuid.UUID],
    counters: dict[str, int],
) -> uuid.UUID:
    fact_id, created = _upsert_returning(
        db,
        models.PersonGender,
        {"person_id": person_id, "value": obs.value, "is_primary": False},
        "uq_person_gender_value",
        select(models.PersonGender.id).where(
            models.PersonGender.person_id == person_id,
            models.PersonGender.value == obs.value,
        ),
    )
    _count_fact(counters, created)
    assertion_id = _create_assertion(
        db,
        source_record,
        obs.field_path,
        obs.source,
        obs.source_primary,
        obs.source_verified,
        identities,
        counters,
    )
    _link_assertion(
        db, models.PersonGenderAssertion, assertion_id, fact_id, "person_gender_id"
    )
    return fact_id


def _apply_locale(
    db: Session,
    person_id: uuid.UUID,
    obs: LocaleObservation,
    source_record: models.SourceRecord,
    identities: dict[tuple[str, str], uuid.UUID],
    counters: dict[str, int],
) -> uuid.UUID:
    fact_id, created = _upsert_returning(
        db,
        models.PersonLocale,
        {"person_id": person_id, "value": obs.value, "is_primary": False},
        "uq_person_locale_value",
        select(models.PersonLocale.id).where(
            models.PersonLocale.person_id == person_id,
            models.PersonLocale.value == obs.value,
        ),
    )
    _count_fact(counters, created)
    assertion_id = _create_assertion(
        db,
        source_record,
        obs.field_path,
        obs.source,
        obs.source_primary,
        obs.source_verified,
        identities,
        counters,
    )
    _link_assertion(
        db, models.PersonLocaleAssertion, assertion_id, fact_id, "person_locale_id"
    )
    return fact_id


def _count_fact(counters: dict[str, int], created: bool) -> None:
    if created:
        counters["facts_created"] += 1
    else:
        counters["facts_reused"] += 1


def _set_primary(
    db: Session, entity: Any, person_id: uuid.UUID, selected_id: uuid.UUID | None
) -> None:
    db.execute(
        update(entity).where(entity.person_id == person_id).values(is_primary=False)
    )
    if selected_id is not None:
        db.execute(
            update(entity).where(entity.id == selected_id).values(is_primary=True)
        )


def _select_primary(
    candidates: list[tuple[uuid.UUID, bool | None, str]],
) -> uuid.UUID | None:
    if not candidates:
        return None
    primary = [candidate for candidate in candidates if candidate[1] is True]
    pool = primary or candidates
    pool.sort(key=lambda candidate: candidate[2])
    return pool[0][0]


def _name_sort_key(obs: NameObservation) -> str:
    return obs.display_name or obs.given_name or obs.family_name or ""


def _date_sort_key(obs: DateObservation) -> str:
    return f"{obs.year or 0:04d}-{obs.month or 0:02d}-{obs.day or 0:02d}"
