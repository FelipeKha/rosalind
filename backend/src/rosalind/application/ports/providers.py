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
