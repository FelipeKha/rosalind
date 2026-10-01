"""Keycloak authentication client (OAuth 2.0 Device Authorization Grant).

The CLI is a public OAuth client: it obtains tokens directly from Keycloak's
device flow, stores them locally, and attaches the access token to backend
requests. Refresh and sign-out are handled here.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import httpx

from cli import config
from cli.storage.credentials import Credentials, CredentialStore

DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


class AuthError(Exception):
    """Raised when authentication with the identity provider fails."""


def _realm_base() -> str:
    return f"{config.keycloak_url().rstrip('/')}/realms/{config.keycloak_realm()}"


def _device_endpoint() -> str:
    return f"{_realm_base()}/protocol/openid-connect/auth/device"


def _token_endpoint() -> str:
    return f"{_realm_base()}/protocol/openid-connect/token"


def _revoke_endpoint() -> str:
    return f"{_realm_base()}/protocol/openid-connect/revoke"


def start_device_flow(scope: str = "openid email profile") -> dict:
    data = {"client_id": config.keycloak_client_id(), "scope": scope}
    try:
        response = httpx.post(_device_endpoint(), data=data, timeout=10.0)
    except httpx.HTTPError as exc:
        raise AuthError(f"unable to reach Keycloak: {exc}") from exc
    if response.status_code != 200:
        raise AuthError(f"device authorization failed ({response.status_code})")
    return response.json()


def poll_device_token(device_code: str, interval: int, timeout: float) -> Credentials:
    """Poll the token endpoint until the user authorizes the device code."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            response = httpx.post(
                _token_endpoint(),
                data={
                    "grant_type": DEVICE_GRANT_TYPE,
                    "device_code": device_code,
                    "client_id": config.keycloak_client_id(),
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"unable to reach Keycloak: {exc}") from exc

        if response.status_code == 200:
            return _credentials_from(response.json())

        error = response.json().get("error") if response.content else None
        if error == "authorization_pending":
            if time.monotonic() >= deadline:
                raise AuthError("timed out waiting for authorization")
            time.sleep(interval)
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise AuthError("authorization denied")
        raise AuthError(f"token exchange failed: {error or response.status_code}")


def refresh(refresh_token: str) -> Credentials:
    try:
        response = httpx.post(
            _token_endpoint(),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": config.keycloak_client_id(),
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise AuthError(f"unable to reach Keycloak: {exc}") from exc
    if response.status_code != 200:
        raise AuthError("failed to refresh access token")
    return _credentials_from(response.json())


def revoke(token: str) -> None:
    try:
        httpx.post(
            _revoke_endpoint(),
            data={"token": token, "client_id": config.keycloak_client_id()},
            timeout=10.0,
        )
    except httpx.HTTPError:
        pass


def _credentials_from(payload: dict) -> Credentials:
    access_token = payload.get("access_token")
    if not access_token:
        raise AuthError("token response missing access_token")
    expires_in = payload.get("expires_in")
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    return Credentials(
        access_token=access_token,
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        token_type=payload.get("token_type", "Bearer"),
    )


def get_access_token(
    store: CredentialStore | None = None, *, force_refresh: bool = False
) -> str | None:
    """Return a usable access token, refreshing it when needed, or ``None``."""
    store = store or CredentialStore()
    credentials = store.load()
    if credentials is None or not credentials.access_token:
        return None

    if not force_refresh and _is_fresh(credentials):
        return credentials.access_token

    if credentials.refresh_token is None:
        return None

    try:
        refreshed = refresh(credentials.refresh_token)
    except AuthError:
        store.clear()
        return None

    store.save(refreshed)
    return refreshed.access_token


def _is_fresh(credentials: Credentials) -> bool:
    if credentials.expires_at is None:
        return True
    return credentials.expires_at > datetime.now(UTC) + timedelta(seconds=5)
