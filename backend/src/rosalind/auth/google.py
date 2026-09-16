"""Google OAuth 2.0 client helpers.

Owns the mechanics of talking to Google: building authorization URLs,
exchanging authorization codes, refreshing tokens, and building API services.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from googleapiclient.discovery import Resource, build  # type: ignore[import-untyped]

from rosalind import config


def _scopes() -> list[str]:
    return [s.strip() for s in config.settings.google_scopes.split(",") if s.strip()]


def to_naive_utc(expiry: datetime | None) -> datetime | None:
    """Convert a datetime to naive UTC (google-auth's internal convention)."""
    if expiry is None:
        return None
    return expiry.astimezone(UTC).replace(tzinfo=None)


def to_aware_utc(expiry: datetime | None) -> datetime | None:
    """Convert a (possibly naive) datetime to timezone-aware UTC."""
    if expiry is None:
        return None
    if expiry.tzinfo is None:
        return expiry.replace(tzinfo=UTC)
    return expiry.astimezone(UTC)


def _client_config() -> dict[str, Any]:
    client_id = config.settings.google_client_id
    client_secret = config.settings.google_client_secret
    if not client_id or not client_secret:
        raise ValueError(
            "ROSALIND_GOOGLE_CLIENT_ID and ROSALIND_GOOGLE_CLIENT_SECRET must be set"
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": config.settings.google_auth_uri,
            "token_uri": config.settings.google_token_uri,
            "redirect_uris": [config.settings.google_redirect_uri],
        }
    }


def build_authorization_url(state: str) -> str:
    """Return the URL the user must visit to authorize Rosalind."""
    flow = Flow.from_client_config(
        _client_config(),
        scopes=_scopes(),
        redirect_uri=config.settings.google_redirect_uri,
    )
    kwargs: dict[str, str] = {
        "access_type": "offline",
        "include_granted_scopes": "true",
    }
    if config.settings.google_auth_prompt:
        kwargs["prompt"] = config.settings.google_auth_prompt
    auth_url, _ = flow.authorization_url(state=state, **kwargs)
    return auth_url


def exchange_code(state: str, code: str) -> Credentials:
    """Exchange an authorization code for credentials (incl. refresh token)."""
    flow = Flow.from_client_config(
        _client_config(),
        scopes=_scopes(),
        redirect_uri=config.settings.google_redirect_uri,
        state=state,
    )
    flow.fetch_token(code=code)
    return flow.credentials


def build_credentials(
    access_token: str,
    refresh_token: str | None,
    scopes: list[str] | None,
    expires_at: datetime | None = None,
) -> Credentials:
    """Reconstruct a Credentials object from persisted (decrypted) values."""
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=config.settings.google_token_uri,
        client_id=config.settings.google_client_id,
        client_secret=config.settings.google_client_secret,
        scopes=scopes,
        expiry=to_naive_utc(expires_at),
    )


def refresh(credentials: Credentials) -> Credentials:
    credentials.refresh(GoogleRequest())
    return credentials


def fetch_userinfo(credentials: Credentials) -> dict[str, str]:
    """Fetch the authenticated user's id, email, and name."""
    service = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
    return service.userinfo().get().execute()


def build_people_service(credentials: Credentials) -> Resource:
    return build("people", "v1", credentials=credentials, cache_discovery=False)
