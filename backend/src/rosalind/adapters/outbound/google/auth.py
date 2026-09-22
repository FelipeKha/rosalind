"""Google OAuth 2.0 client helpers.

Owns the mechanics of talking to Google: building authorization URLs,
exchanging authorization codes, refreshing tokens, and building API services.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from googleapiclient.discovery import Resource, build  # type: ignore[import-untyped]

from rosalind import config
from rosalind.adapters.outbound.google.errors import ProviderError

GOOGLE_REVOKE_URI = "https://oauth2.googleapis.com/revoke"

# https://developers.google.com/identity/protocols/oauth2/scopes?utm_source=chatgpt.com
# https://developers.google.com/people/api/rest/v1/people/get
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts.other.readonly",
    "https://www.googleapis.com/auth/directory.readonly",
    "https://www.googleapis.com/auth/profile.agerange.read",
    "https://www.googleapis.com/auth/profile.emails.read",
    "https://www.googleapis.com/auth/profile.language.read",
    "https://www.googleapis.com/auth/user.addresses.read",
    "https://www.googleapis.com/auth/user.birthday.read",
    "https://www.googleapis.com/auth/user.emails.read",
    "https://www.googleapis.com/auth/user.gender.read",
    "https://www.googleapis.com/auth/user.organization.read",
    "https://www.googleapis.com/auth/user.phonenumbers.read",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/profile.language.read",
]


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


def _build_flow(state: str | None = None, code_verifier: str | None = None) -> Flow:
    kwargs: dict[str, Any] = {"redirect_uri": config.settings.google_redirect_uri}
    if state is not None:
        kwargs["state"] = state
    if code_verifier is not None:
        kwargs["code_verifier"] = code_verifier
        kwargs["autogenerate_code_verifier"] = False
    return Flow.from_client_config(_client_config(), scopes=GOOGLE_SCOPES, **kwargs)


def build_authorization_url(state: str) -> tuple[str, str]:
    """Return the URL the user must visit and its PKCE code verifier."""
    flow = _build_flow()
    kwargs: dict[str, str] = {
        "access_type": "offline",
        "include_granted_scopes": "true",
    }
    if config.settings.google_auth_prompt:
        kwargs["prompt"] = config.settings.google_auth_prompt
    auth_url, _ = flow.authorization_url(state=state, **kwargs)

    code_verifier = flow.code_verifier
    if code_verifier is None:
        raise ValueError("failed to generate a PKCE code verifier")
    return auth_url, code_verifier


def exchange_code(state: str, code: str, code_verifier: str | None) -> Credentials:
    """Exchange an authorization code for credentials (incl. refresh token)."""
    flow = _build_flow(state=state, code_verifier=code_verifier)
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


def revoke(token: str) -> None:
    """Revoke a token at Google so it can no longer be used or refreshed."""
    try:
        response = GoogleRequest().session.post(
            GOOGLE_REVOKE_URI,
            data={"token": token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ProviderError(f"failed to revoke Google token: {exc}") from exc


def fetch_userinfo(credentials: Credentials) -> dict[str, str]:
    """Fetch the authenticated user's id, email, and name."""
    service = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
    return service.userinfo().get().execute()


def build_people_service(credentials: Credentials) -> Resource:
    return build("people", "v1", credentials=credentials, cache_discovery=False)
