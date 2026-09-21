"""Read-facing domain types shared by the API and MCP layers.

These are plain value objects: no SQL, no HTTP, no MCP concerns. They mirror
the ``agent.person_profile`` view (the canonical read model).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class PersonProfile:
    """Resolved, read-facing shape of a person.

    Derived from the canonical ``core`` model via ``agent.person_profile``;
    never a source of truth on its own.
    """

    person_id: uuid.UUID
    display_name: str | None
    given_name: str | None
    family_name: str | None
    primary_email: str | None
    email_verified: bool | None
    gender: str | None
    locale: str | None
    birth_year: int | None
    birth_month: int | None
    birth_day: int | None
