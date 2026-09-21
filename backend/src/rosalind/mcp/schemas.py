"""MCP-facing response models.

Deliberately separate from the REST schemas: MCP is consumed by an AI
application, not a software developer, so its contract may diverge over time
(e.g. exposing birth_year/month/day as a single ``birth_date``). Keeping the
two boundaries independent avoids one constraining the other.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class PersonProfileResult(BaseModel):
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
