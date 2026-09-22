"""Persistence for the person read model.

The only module that talks SQL for the person profile. It reads the
``agent.person_profile`` view (the derived read model) and maps rows to
``PersonProfile`` value objects; everything above this works in domain terms.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from rosalind.services.read_models import PersonProfile

_PROFILE_QUERY = "select * from agent.person_profile"


class PostgresPersonRepository:
    def search(
        self, db: Session, query: str, limit: int
    ) -> list[PersonProfile]:
        rows = db.execute(
            text(
                f"{_PROFILE_QUERY} "
                "where display_name ilike '%' || :q || '%' "
                "or primary_email ilike '%' || :q || '%' "
                "limit :limit"
            ),
            {"q": query, "limit": limit},
        ).all()
        return [self._to_profile(row) for row in rows]

    def list_all(self, db: Session, limit: int) -> list[PersonProfile]:
        rows = db.execute(
            text(
                f"{_PROFILE_QUERY} order by display_name nulls last limit :limit"
            ),
            {"limit": limit},
        ).all()
        return [self._to_profile(row) for row in rows]

    def get(self, db: Session, person_id: uuid.UUID) -> PersonProfile | None:
        row = db.execute(
            text(f"{_PROFILE_QUERY} where person_id = :person_id"),
            {"person_id": person_id},
        ).first()
        return self._to_profile(row) if row is not None else None

    @staticmethod
    def _to_profile(row: Any) -> PersonProfile:
        return PersonProfile(
            person_id=row.person_id,
            display_name=row.display_name,
            given_name=row.given_name,
            family_name=row.family_name,
            primary_email=row.primary_email,
            email_verified=row.email_verified,
            gender=row.gender,
            locale=row.locale,
            birth_year=row.birth_year,
            birth_month=row.birth_month,
            birth_day=row.birth_day,
        )
