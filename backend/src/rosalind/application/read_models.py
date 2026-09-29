"""Read-facing value objects returned by application services.

These are plain value objects: no SQL, no HTTP, no MCP concerns. They mirror the
``agent.person_profile`` view (the canonical read model) and are shared by the
REST API and MCP adapters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from rosalind.domain.account import Account


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


@dataclass(frozen=True)
class CurrentAccount:
    """The authenticated account's identity, resolved for the current user.

    A derived projection: ``account_id``/``self_person_id``/``created_at`` come
    from the persisted ``Account``, while ``subject`` and the profile fields
    come from the IdP-issued token. Keycloak remains the source of truth for
    profile data; Rosalind only persists the identity mapping.
    """

    account_id: uuid.UUID
    self_person_id: uuid.UUID | None
    created_at: datetime
    subject: str
    email: str | None
    preferred_username: str | None
    given_name: str | None
    family_name: str | None


def current_account_from(
    account: Account,
    *,
    subject: str,
    email: str | None,
    preferred_username: str | None,
    given_name: str | None,
    family_name: str | None,
) -> CurrentAccount:
    """Project a persisted ``Account`` plus token claims into a read model."""
    return CurrentAccount(
        account_id=account.id,
        self_person_id=account.self_person_id,
        created_at=account.created_at,
        subject=subject,
        email=email,
        preferred_username=preferred_username,
        given_name=given_name,
        family_name=family_name,
    )
