"""Ports (interfaces) for external provider gateways.

Concrete implementations live in ``adapters.outbound`` (e.g. ``google.auth`` and
``google.people``). Application services depend on these Protocols and the
provider-agnostic value objects defined here, never on a provider SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderCredentials:
    """Provider-agnostic OAuth credential bundle.

    ``expires_at`` is always timezone-aware UTC (or ``None`` when the provider
    does not report an expiry).
    """

    access_token: str
    refresh_token: str | None = None
    scopes: list[str] | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class UserIdentity:
    """The authenticated user's identity at a provider."""

    account_identifier: str
    display_name: str | None = None


@dataclass(frozen=True)
class ContactsFetch:
    """A full set of provider contacts plus the incremental sync cursor.

    ``contacts`` holds the raw provider payloads (each ready to be persisted as
    evidence and canonicalized). ``next_sync_token`` and ``sync_parameters``
    establish the baseline for a later incremental sync: the token is only
    reusable with the exact request parameters captured in ``sync_parameters``.
    """

    contacts: tuple[dict[str, Any], ...]
    next_sync_token: str | None
    sync_parameters: dict[str, Any] | None


class AuthGateway(Protocol):
    def build_authorization_url(self, state: str) -> tuple[str, str]: ...

    def exchange_code(
        self, state: str, code: str, code_verifier: str | None
    ) -> ProviderCredentials: ...

    def fetch_userinfo(self, credentials: ProviderCredentials) -> UserIdentity: ...

    def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials: ...

    def revoke(self, token: str) -> None: ...


class PeopleGateway(Protocol):
    def fetch_profile(self, credentials: ProviderCredentials) -> dict[str, Any]: ...

    def fetch_contacts(self, credentials: ProviderCredentials) -> ContactsFetch: ...
