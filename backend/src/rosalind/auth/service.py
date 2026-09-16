"""Provider authentication orchestration."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from google.oauth2.credentials import Credentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind import models, security
from rosalind.auth import google as google_auth
from rosalind.auth.errors import InvalidStateError, ProviderError, TokenNotFoundError

STATUS_PENDING = "pending"
STATUS_CONNECTED = "connected"
STATUS_EXPIRED = "expired"
STATUS_NOT_FOUND = "not_found"

_AUTH_REQUEST_TTL = timedelta(minutes=10)


@dataclass
class ConnectStart:
    source_account_id: uuid.UUID
    auth_url: str
    state: str


@dataclass
class AuthStatus:
    status: str
    source_account_id: uuid.UUID | None = None
    display_name: str | None = None


def start_connect(db: Session, provider: str = "google") -> ConnectStart:
    account = models.SourceAccount(provider=provider)
    db.add(account)
    db.flush()

    state = secrets.token_urlsafe(32)
    db.add(
        models.OAuthAuthRequest(
            state=state,
            source_account_id=account.id,
            expires_at=datetime.now(UTC) + _AUTH_REQUEST_TTL,
        )
    )

    auth_url = google_auth.build_authorization_url(state)
    db.commit()
    return ConnectStart(source_account_id=account.id, auth_url=auth_url, state=state)


def complete_connect(db: Session, state: str, code: str) -> models.SourceAccount:
    request = db.get(models.OAuthAuthRequest, state)
    if request is None or request.expires_at < datetime.now(UTC):
        raise InvalidStateError("authorization request is unknown or expired")

    try:
        credentials = google_auth.exchange_code(state, code)
        userinfo = google_auth.fetch_userinfo(credentials)
    except ProviderError:
        raise
    except Exception as exc:  # provider boundary
        raise ProviderError(
            f"failed to exchange Google authorization code: {exc}"
        ) from exc

    account = db.get(models.SourceAccount, request.source_account_id)
    if account is None:
        raise InvalidStateError("authorization request references an unknown account")

    account.account_identifier = userinfo.get("id")
    account.display_name = userinfo.get("name")
    _upsert_credential(account, credentials, provider="google")

    request.status = STATUS_CONNECTED
    db.commit()
    return account


def get_status(db: Session, state: str) -> AuthStatus:
    request = db.get(models.OAuthAuthRequest, state)
    if request is None:
        return AuthStatus(status=STATUS_NOT_FOUND)

    if request.status == STATUS_CONNECTED:
        account = db.get(models.SourceAccount, request.source_account_id)
        return AuthStatus(
            status=STATUS_CONNECTED,
            source_account_id=request.source_account_id,
            display_name=account.display_name if account else None,
        )

    if request.expires_at < datetime.now(UTC):
        return AuthStatus(
            status=STATUS_EXPIRED, source_account_id=request.source_account_id
        )

    return AuthStatus(
        status=STATUS_PENDING, source_account_id=request.source_account_id
    )


def load_credentials(
    db: Session, provider: str = "google"
) -> tuple[models.SourceAccount, Credentials]:
    credential = db.scalars(
        select(models.OAuthCredential)
        .where(models.OAuthCredential.provider == provider)
        .order_by(models.OAuthCredential.created_at.desc())
    ).first()
    if credential is None:
        raise TokenNotFoundError(f"no stored credentials for provider {provider!r}")

    credentials = google_auth.build_credentials(
        access_token=security.decrypt_secret(credential.access_token_encrypted),
        refresh_token=(
            security.decrypt_secret(credential.refresh_token_encrypted)
            if credential.refresh_token_encrypted
            else None
        ),
        scopes=credential.scope.split() if credential.scope else None,
        expires_at=credential.expires_at,
    )

    if credentials.expired:
        try:
            google_auth.refresh(credentials)
        except Exception as exc:  # provider boundary
            raise ProviderError(f"failed to refresh Google credentials: {exc}") from exc
        credential.access_token_encrypted = security.encrypt_secret(credentials.token)
        credential.expires_at = google_auth.to_aware_utc(credentials.expiry)
        db.commit()

    return credential.source_account, credentials


def _upsert_credential(
    account: models.SourceAccount,
    credentials: Credentials,
    provider: str,
) -> None:
    credential = next(
        (c for c in account.credentials if c.provider == provider),
        None,
    )
    if credential is None:
        credential = models.OAuthCredential(provider=provider)
        account.credentials.append(credential)

    credential.token_type = "Bearer"  # nosec B105
    credential.access_token_encrypted = security.encrypt_secret(credentials.token)
    credential.refresh_token_encrypted = (
        security.encrypt_secret(credentials.refresh_token)
        if credentials.refresh_token
        else None
    )
    credential.scope = " ".join(credentials.scopes) if credentials.scopes else None
    credential.expires_at = google_auth.to_aware_utc(credentials.expiry)
