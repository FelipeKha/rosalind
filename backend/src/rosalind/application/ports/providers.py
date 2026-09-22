"""Ports (interfaces) for external provider gateways.

Concrete implementations live in ``adapters.outbound.google.gateways``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from google.oauth2.credentials import Credentials


class GoogleAuthGateway(Protocol):
    def build_authorization_url(self, state: str) -> tuple[str, str]: ...

    def exchange_code(
        self, state: str, code: str, code_verifier: str | None
    ) -> Credentials: ...

    def fetch_userinfo(self, credentials: Credentials) -> dict[str, str]: ...

    def build_credentials(
        self,
        *,
        access_token: str,
        refresh_token: str | None,
        scopes: list[str] | None,
        expires_at: datetime | None = None,
    ) -> Credentials: ...

    def refresh(self, credentials: Credentials) -> Credentials: ...

    def revoke(self, token: str) -> None: ...

    def to_aware_utc(self, expiry: datetime | None) -> datetime | None: ...


class GooglePeopleGateway(Protocol):
    def fetch_profile(self, credentials: Credentials) -> dict[str, Any]: ...
