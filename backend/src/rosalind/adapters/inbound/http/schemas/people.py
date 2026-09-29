"""Response schemas for the person read endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class PersonProfileResponse(BaseModel):
    person_id: uuid.UUID
    display_name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    primary_email: str | None = None
    email_verified: bool | None = None
    gender: str | None = None
    locale: str | None = None
    birth_year: int | None = None
    birth_month: int | None = None
    birth_day: int | None = None
