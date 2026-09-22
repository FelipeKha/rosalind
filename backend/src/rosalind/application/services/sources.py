"""Application service for source management.

A source is a connection to an external data holder (e.g. a Google account).
It has a human-facing ``name`` (the CLI slug) and an immutable provider identity
(``provider`` + ``account_identifier``). Connecting (OAuth) and disconnecting
(revoking credentials) happen here; imports and raw data are never touched.
"""

from __future__ import annotations

import secrets
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind import security
from rosalind.adapters.outbound.persistence import models
from rosalind.application.errors import (
    InvalidStateError,
    ProviderError,
    SourceNotFoundError,
    TokenNotFoundError,
)
from rosalind.application.ports.providers import AuthGateway, ProviderCredentials

STATUS_PENDING = "pending"
STATUS_CONNECTED = "connected"
STATUS_EXPIRED = "expired"
STATUS_NOT_FOUND = "not_found"
STATUS_DISCONNECTED = "disconnected"
STATUS_ALREADY_DISCONNECTED = "already_disconnected"

SOURCE_CONNECTED = "connected"
SOURCE_DISCONNECTED = "disconnected"

_AUTH_REQUEST_TTL = timedelta(minutes=10)


@dataclass
class ConnectStart:
    source_id: uuid.UUID
    auth_url: str
    state: str


@dataclass
class AuthStatus:
    status: str
    source_id: uuid.UUID | None = None
    display_name: str | None = None


@dataclass
class DisconnectResult:
    status: str
    revoked: bool


def default_source_name(provider: str) -> str:
    """Return the default CLI slug for a provider (``google`` → ``google``)."""
    return provider


class SourceService:
    def __init__(self, auth: AuthGateway):
        self._auth = auth

    def resolve_source(self, db: Session, name: str) -> models.SourceAccount:
        account = db.scalar(
            select(models.SourceAccount).where(models.SourceAccount.name == name)
        )
        if account is None:
            raise SourceNotFoundError(f"source {name!r} not found")
        return account

    def get_source(self, db: Session, source_id: uuid.UUID) -> models.SourceAccount:
        account = db.get(models.SourceAccount, source_id)
        if account is None:
            raise SourceNotFoundError(f"source {source_id} not found")
        return account

    def list_sources(self, db: Session) -> list[models.SourceAccount]:
        return list(
            db.scalars(
                select(models.SourceAccount).order_by(models.SourceAccount.created_at)
            ).all()
        )

    def create_source(
        self, db: Session, provider: str, name: str
    ) -> models.SourceAccount:
        account = models.SourceAccount(provider=provider, name=name)
        db.add(account)
        db.commit()
        db.refresh(account)
        return account

    def is_connected(self, db: Session, source_id: uuid.UUID) -> bool:
        return (
            db.scalar(
                select(models.OAuthCredential.id).where(
                    models.OAuthCredential.source_account_id == source_id
                )
            )
            is not None
        )

    def start_connect(
        self, db: Session, provider: str, name: str | None = None
    ) -> ConnectStart:
        """Begin OAuth for a provider, stashing the requested name on the auth request.

        The placeholder account starts without a name so a reconnect never collides
        with the ``uq_source_account_name`` constraint before OAuth resolves the
        account's identity; the name is applied in ``complete_connect``.
        """
        account = models.SourceAccount(provider=provider, name=None)
        db.add(account)
        db.flush()

        state = secrets.token_urlsafe(32)
        auth_url, code_verifier = self._auth.build_authorization_url(state)
        db.add(
            models.OAuthAuthRequest(
                state=state,
                source_account_id=account.id,
                source_name=name or default_source_name(provider),
                code_verifier=code_verifier,
                expires_at=datetime.now(UTC) + _AUTH_REQUEST_TTL,
            )
        )

        db.commit()
        return ConnectStart(source_id=account.id, auth_url=auth_url, state=state)

    def complete_connect(
        self, db: Session, state: str, code: str
    ) -> models.SourceAccount:
        request = db.get(models.OAuthAuthRequest, state)
        if request is None or request.expires_at < datetime.now(UTC):
            raise InvalidStateError("authorization request is unknown or expired")
        if request.consumed_at is not None:
            raise InvalidStateError("authorization request was already consumed")

        pending = db.get(models.SourceAccount, request.source_account_id)
        if pending is None:
            raise InvalidStateError(
                "authorization request references an unknown account"
            )
        provider = pending.provider

        try:
            credentials = self._auth.exchange_code(state, code, request.code_verifier)
            identity = self._auth.fetch_userinfo(credentials)
        except ProviderError:
            raise
        except Exception as exc:  # provider boundary
            raise ProviderError(
                f"failed to exchange authorization code: {exc}"
            ) from exc

        account = db.scalar(
            select(models.SourceAccount).where(
                models.SourceAccount.provider == provider,
                models.SourceAccount.account_identifier == identity.account_identifier,
            )
        )

        if account is not None:
            if pending.id != account.id:
                request.source_account_id = account.id
                db.flush()
                db.delete(pending)
        else:
            account = pending
            account.account_identifier = identity.account_identifier

        # The name is the current CLI slug, so assign it on every connect. A
        # re-authenticated account must pick up the current (or explicitly
        # requested) name rather than keeping a stale one.
        account.name = request.source_name
        account.display_name = identity.display_name
        self._upsert_credential(account, credentials, provider=provider)

        request.status = STATUS_CONNECTED
        request.consumed_at = datetime.now(UTC)
        db.commit()
        return account

    def get_connect_status(self, db: Session, state: str) -> AuthStatus:
        request = db.get(models.OAuthAuthRequest, state)
        if request is None:
            return AuthStatus(status=STATUS_NOT_FOUND)

        if request.status == STATUS_CONNECTED:
            account = db.get(models.SourceAccount, request.source_account_id)
            return AuthStatus(
                status=STATUS_CONNECTED,
                source_id=request.source_account_id,
                display_name=account.display_name if account else None,
            )

        if request.expires_at < datetime.now(UTC):
            return AuthStatus(
                status=STATUS_EXPIRED, source_id=request.source_account_id
            )

        return AuthStatus(status=STATUS_PENDING, source_id=request.source_account_id)

    def disconnect(self, db: Session, source_id: uuid.UUID) -> DisconnectResult:
        """Revoke and remove stored credentials for a source account.

        Revocation at the provider is best-effort; local credentials are removed
        regardless so the backend no longer holds a live grant. The source account,
        its imports, and raw/canonical data are intentionally left untouched.
        """
        source = self.get_source(db, source_id)
        credentials = db.scalars(
            select(models.OAuthCredential).where(
                models.OAuthCredential.source_account_id == source.id
            )
        ).all()
        if not credentials:
            return DisconnectResult(status=STATUS_ALREADY_DISCONNECTED, revoked=False)

        revoked = False
        for credential in credentials:
            token = _revokable_token(credential)
            if token is not None:
                with suppress(ProviderError):
                    self._auth.revoke(token)
                    revoked = True
            db.delete(credential)

        db.commit()
        return DisconnectResult(status=STATUS_DISCONNECTED, revoked=revoked)

    def load_credentials(
        self, db: Session, source_id: uuid.UUID
    ) -> tuple[models.SourceAccount, ProviderCredentials]:
        credential = db.scalars(
            select(models.OAuthCredential)
            .where(models.OAuthCredential.source_account_id == source_id)
            .order_by(models.OAuthCredential.created_at.desc())
        ).first()
        if credential is None:
            raise TokenNotFoundError(f"no stored credentials for source {source_id}")

        credentials = ProviderCredentials(
            access_token=security.decrypt_secret(credential.access_token_encrypted),
            refresh_token=(
                security.decrypt_secret(credential.refresh_token_encrypted)
                if credential.refresh_token_encrypted
                else None
            ),
            scopes=credential.scope.split() if credential.scope else None,
            expires_at=credential.expires_at,
        )

        if (
            credentials.expires_at is not None
            and credentials.expires_at <= datetime.now(UTC)
        ):
            try:
                credentials = self._auth.refresh(credentials)
            except Exception as exc:  # provider boundary
                raise ProviderError(f"failed to refresh credentials: {exc}") from exc
            credential.access_token_encrypted = security.encrypt_secret(
                credentials.access_token
            )
            credential.expires_at = credentials.expires_at
            db.commit()

        return credential.source_account, credentials

    def _upsert_credential(
        self,
        account: models.SourceAccount,
        credentials: ProviderCredentials,
        provider: str,
    ) -> None:
        session = Session.object_session(account)
        if session is None:
            raise ProviderError("source account is not attached to a session")
        credential = session.scalars(
            select(models.OAuthCredential).where(
                models.OAuthCredential.source_account_id == account.id,
                models.OAuthCredential.provider == provider,
            )
        ).first()
        if credential is None:
            credential = models.OAuthCredential(provider=provider)
            account.credentials.append(credential)

        credential.token_type = "Bearer"  # nosec B105
        credential.access_token_encrypted = security.encrypt_secret(
            credentials.access_token
        )
        credential.refresh_token_encrypted = (
            security.encrypt_secret(credentials.refresh_token)
            if credentials.refresh_token
            else None
        )
        credential.scope = " ".join(credentials.scopes) if credentials.scopes else None
        credential.expires_at = credentials.expires_at


def _revokable_token(credential: models.OAuthCredential) -> str | None:
    encrypted = credential.refresh_token_encrypted or credential.access_token_encrypted
    if encrypted is None:
        return None
    try:
        return security.decrypt_secret(encrypted)
    except security.SecurityError:
        return None
