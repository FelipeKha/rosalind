"""Canonicalize a person observation into the ``core`` schema.

Idempotency is database-driven: PostgreSQL uniqueness constraints plus
``INSERT ... ON CONFLICT`` guard every fact and assertion, so re-processing the
same source record (or an identical payload) never creates duplicates.

Primary selection treats ``source_primary`` as an input signal, not an
invariant: it is Rosalind that decides ``is_primary``.

This module owns canonicalization *decisions* (which fact is primary, sorting,
conflict detection) and delegates all persistence to the
``PersonCanonicalRepository`` port (reached via the injected ``UnitOfWork``).
It never imports SQLAlchemy or concrete models.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from rosalind.application.canonicalization.email import normalize_email
from rosalind.application.errors import EntityResolutionConflictError
from rosalind.application.ports.repositories import FactUpsertResult
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.person import (
    DateObservation,
    NameObservation,
    PersonObservation,
)
from rosalind.domain.source import SourceAccount, SourceRecord, SourceRef


@dataclass(frozen=True)
class CanonicalizationResult:
    person_id: uuid.UUID
    created: bool
    facts_created: int
    facts_reused: int
    assertions_created: int


class CanonicalizationService:
    def canonicalize(
        self,
        uow: UnitOfWork,
        source_account: SourceAccount,
        source_record: SourceRecord,
        observation: PersonObservation,
    ) -> CanonicalizationResult:
        """Persist canonical facts and provenance for one source record.

        Runs within the caller's transaction; flushes but does not commit.
        """
        person_id, created = self._resolve_or_create_person(
            uow, source_account, observation.source_identities
        )
        identities = uow.person_canonical.upsert_source_identity(
            source_account_id=source_account.id,
            person_id=person_id,
            refs=observation.source_identities,
            resource_name=source_record.external_id,
        )

        counters = {"facts_created": 0, "facts_reused": 0, "assertions_created": 0}

        name_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
        for name_obs in observation.names:
            result = uow.person_canonical.upsert_name(
                person_id=person_id,
                observation=name_obs,
                source_record_id=source_record.id,
                source_identity_id=_source_identity_id(identities, name_obs.source),
            )
            self._count_fact(counters, result)
            name_candidates.append(
                (result.fact_id, name_obs.source_primary, _name_sort_key(name_obs))
            )

        email_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
        for email_obs in observation.emails:
            result = uow.person_canonical.upsert_email(
                person_id=person_id,
                observation=email_obs,
                source_record_id=source_record.id,
                source_identity_id=_source_identity_id(identities, email_obs.source),
            )
            self._count_fact(counters, result)
            email_candidates.append(
                (
                    result.fact_id,
                    email_obs.source_primary,
                    normalize_email(email_obs.value),
                )
            )

        date_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
        for date_obs in observation.dates:
            result = uow.person_canonical.upsert_date(
                person_id=person_id,
                observation=date_obs,
                source_record_id=source_record.id,
                source_identity_id=_source_identity_id(identities, date_obs.source),
            )
            self._count_fact(counters, result)
            date_candidates.append(
                (result.fact_id, date_obs.source_primary, _date_sort_key(date_obs))
            )

        gender_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
        for gender_obs in observation.genders:
            result = uow.person_canonical.upsert_gender(
                person_id=person_id,
                observation=gender_obs,
                source_record_id=source_record.id,
                source_identity_id=_source_identity_id(identities, gender_obs.source),
            )
            self._count_fact(counters, result)
            gender_candidates.append(
                (result.fact_id, gender_obs.source_primary, gender_obs.value)
            )

        locale_candidates: list[tuple[uuid.UUID, bool | None, str]] = []
        for locale_obs in observation.locales:
            result = uow.person_canonical.upsert_locale(
                person_id=person_id,
                observation=locale_obs,
                source_record_id=source_record.id,
                source_identity_id=_source_identity_id(identities, locale_obs.source),
            )
            self._count_fact(counters, result)
            locale_candidates.append(
                (result.fact_id, locale_obs.source_primary, locale_obs.value)
            )

        uow.person_canonical.set_name_primary(
            person_id=person_id, fact_id=_select_primary(name_candidates)
        )
        uow.person_canonical.set_email_primary(
            person_id=person_id, fact_id=_select_primary(email_candidates)
        )
        uow.person_canonical.set_date_primary(
            person_id=person_id, fact_id=_select_primary(date_candidates)
        )
        uow.person_canonical.set_gender_primary(
            person_id=person_id, fact_id=_select_primary(gender_candidates)
        )
        uow.person_canonical.set_locale_primary(
            person_id=person_id, fact_id=_select_primary(locale_candidates)
        )

        uow.flush()
        return CanonicalizationResult(
            person_id=person_id,
            created=created,
            facts_created=counters["facts_created"],
            facts_reused=counters["facts_reused"],
            assertions_created=counters["assertions_created"],
        )

    def _resolve_or_create_person(
        self,
        uow: UnitOfWork,
        source_account: SourceAccount,
        refs: tuple[SourceRef, ...],
    ) -> tuple[uuid.UUID, bool]:
        person_ids = uow.person_canonical.find_person_ids(
            source_account_id=source_account.id, refs=refs
        )
        if len(person_ids) > 1:
            raise EntityResolutionConflictError(
                "source identities resolve to multiple persons: "
                f"{sorted(str(p) for p in person_ids)}"
            )
        if len(person_ids) == 1:
            return person_ids.pop(), False

        return uow.person_canonical.create_person(), True

    @staticmethod
    def _count_fact(counters: dict[str, int], result: FactUpsertResult) -> None:
        if result.fact_created:
            counters["facts_created"] += 1
        else:
            counters["facts_reused"] += 1
        if result.assertion_created:
            counters["assertions_created"] += 1


def _source_identity_id(
    identities: dict[SourceRef, uuid.UUID], source: SourceRef | None
) -> uuid.UUID | None:
    return identities.get(source) if source else None


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
