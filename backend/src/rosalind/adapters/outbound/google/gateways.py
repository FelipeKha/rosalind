"""Concrete Google provider gateways.

Thin adapters that satisfy ``application.ports.providers`` by delegating to the
low-level ``auth`` and ``people`` module helpers. The application layer depends
on the port Protocols, never on these classes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from google.oauth2.credentials import Credentials

from rosalind.adapters.outbound.google import auth as google_auth
from rosalind.adapters.outbound.google import people as google_people


class GoogleAuthGatewayImpl:
    def build_authorization_url(self, state: str) -> tuple[str, str]:
        return google_auth.build_authorization_url(state)

    def exchange_code(
        self, state: str, code: str, code_verifier: str | None
    ) -> Credentials:
        return google_auth.exchange_code(state, code, code_verifier)

    def fetch_userinfo(self, credentials: Credentials) -> dict[str, str]:
        return google_auth.fetch_userinfo(credentials)

    def build_credentials(
        self,
        *,
        access_token: str,
        refresh_token: str | None,
        scopes: list[str] | None,
        expires_at: datetime | None = None,
    ) -> Credentials:
        return google_auth.build_credentials(
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=scopes,
            expires_at=expires_at,
        )

    def refresh(self, credentials: Credentials) -> Credentials:
        return google_auth.refresh(credentials)

    def revoke(self, token: str) -> None:
        google_auth.revoke(token)

    def to_aware_utc(self, expiry: datetime | None) -> datetime | None:
        return google_auth.to_aware_utc(expiry)


class GooglePeopleGatewayImpl:
    def fetch_profile(self, credentials: Credentials) -> dict[str, Any]:
        return google_people.fetch_profile(credentials)
