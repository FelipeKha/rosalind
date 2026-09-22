"""Application service for source management.

A source is a connection to an external data holder (e.g. a Google account).
It has a human-facing ``name`` (the CLI slug) and an immutable provider identity
(``provider`` + ``account_identifier``). Connecting (OAuth) and disconnecting
(revoking credentials) happen here; imports and raw data are never touched.

Account CRUD goes through the ``SourceAccountRepository`` port; OAuth credentials
and authorization requests go through the ``OAuthCredentialRepository`` and
``OAuthAuthRequestRepository`` ports.
"""

from __future__ import annotations

import secrets
import uuid
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from rosalind.application.errors import (
    InvalidStateError,
    ProviderError,
    SourceNotFoundError,
    TokenNotFoundError,
)
from rosalind.application.ports.providers import AuthGateway, ProviderCredentials
from rosalind.application.ports.repositories import (
    OAuthAuthRequestRepository,
    OAuthCredentialRepository,
    SourceAccountRepository,
    StoredCredential,
)
from rosalind.domain.source import SourceAccount

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
    def __init__(
        self,
        auth: AuthGateway,
        accounts: SourceAccountRepository,
        credentials: OAuthCredentialRepository,
        auth_requests: OAuthAuthRequestRepository,
    ):
        self._auth = auth
        self._accounts = accounts
        self._credentials = credentials
        self._auth_requests = auth_requests

    def resolve_source(self, db: Session, name: str) -> SourceAccount:
        account = self._accounts.get_by_name(db, name)
        if account is None:
            raise SourceNotFoundError(f"source {name!r} not found")
        return account

    def get_source(self, db: Session, source_id: uuid.UUID) -> SourceAccount:
        account = self._accounts.get(db, source_id)
        if account is None:
            raise SourceNotFoundError(f"source {source_id} not found")
        return account

    def list_sources(self, db: Session) -> list[SourceAccount]:
        return self._accounts.list(db)

    def create_source(self, db: Session, provider: str, name: str) -> SourceAccount:
        account = self._accounts.create(db, provider=provider, name=name)
        db.commit()
        return account

    def is_connected(self, db: Session, source_id: uuid.UUID) -> bool:
        return self._credentials.exists(db, source_id)

    def start_connect(
        self, db: Session, provider: str, name: str | None = None
    ) -> ConnectStart:
        """Begin OAuth for a provider, stashing the requested name on the auth request.

        The placeholder account starts without a name so a reconnect never collides
        with the ``uq_source_account_name`` constraint before OAuth resolves the
        account's identity; the name is applied in ``complete_connect``.
        """
        account = self._accounts.create(db, provider=provider, name=None)

        state = secrets.token_urlsafe(32)
        auth_url, code_verifier = self._auth.build_authorization_url(state)
        self._auth_requests.create(
            db,
            state=state,
            source_account_id=account.id,
            source_name=name or default_source_name(provider),
            code_verifier=code_verifier,
            expires_at=datetime.now(UTC) + _AUTH_REQUEST_TTL,
        )

        db.commit()
        return ConnectStart(source_id=account.id, auth_url=auth_url, state=state)

    def complete_connect(self, db: Session, state: str, code: str) -> SourceAccount:
        request = self._auth_requests.get(db, state)
        if request is None or request.expires_at < datetime.now(UTC):
            raise InvalidStateError("authorization request is unknown or expired")
        if request.consumed_at is not None:
            raise InvalidStateError("authorization request was already consumed")

        pending = self._accounts.get(db, request.source_account_id)
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

        account = self._accounts.get_by_identity(
            db, provider, identity.account_identifier
        )

        if account is not None:
            if pending.id != account.id:
                self._auth_requests.reassign(db, state, account.id)
                self._accounts.delete(db, pending.id)
        else:
            account = pending
            account = self._accounts.update(
                db,
                replace(account, account_identifier=identity.account_identifier),
            )

        # The name is the current CLI slug, so assign it on every connect. A
        # re-authenticated account must pick up the current (or explicitly
        # requested) name rather than keeping a stale one.
        account = self._accounts.update(
            db,
            replace(
                account,
                name=request.source_name,
                display_name=identity.display_name,
            ),
        )
        self._credentials.upsert(
            db,
            account_id=account.id,
            provider=provider,
            access_token=credentials.access_token,
            refresh_token=credentials.refresh_token,
            scopes=credentials.scopes,
            expires_at=credentials.expires_at,
        )

        self._auth_requests.mark_connected(db, state, datetime.now(UTC))
        db.commit()
        return account

    def get_connect_status(self, db: Session, state: str) -> AuthStatus:
        request = self._auth_requests.get(db, state)
        if request is None:
            return AuthStatus(status=STATUS_NOT_FOUND)

        if request.status == STATUS_CONNECTED:
            account = self._accounts.get(db, request.source_account_id)
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
        stored = self._credentials.list_all(db, source.id)
        if not stored:
            return DisconnectResult(status=STATUS_ALREADY_DISCONNECTED, revoked=False)

        revoked = False
        for credential in stored:
            token = _revokable_token(credential)
            if token is not None:
                with suppress(ProviderError):
                    self._auth.revoke(token)
                    revoked = True

        self._credentials.delete_all(db, source.id)
        db.commit()
        return DisconnectResult(status=STATUS_DISCONNECTED, revoked=revoked)

    def load_credentials(
        self, db: Session, source_id: uuid.UUID
    ) -> tuple[SourceAccount, ProviderCredentials]:
        stored = self._credentials.get_latest(db, source_id)
        if stored is None:
            raise TokenNotFoundError(f"no stored credentials for source {source_id}")

        if stored.access_token is None:
            raise TokenNotFoundError(f"no usable credentials for source {source_id}")

        credentials = ProviderCredentials(
            access_token=stored.access_token,
            refresh_token=stored.refresh_token,
            scopes=stored.scopes,
            expires_at=stored.expires_at,
        )

        if (
            credentials.expires_at is not None
            and credentials.expires_at <= datetime.now(UTC)
        ):
            try:
                credentials = self._auth.refresh(credentials)
            except Exception as exc:  # provider boundary
                raise ProviderError(f"failed to refresh credentials: {exc}") from exc
            self._credentials.update_tokens(
                db,
                account_id=source_id,
                provider=stored.provider,
                access_token=credentials.access_token,
                expires_at=credentials.expires_at,
            )
            db.commit()

        account = self._accounts.get(db, source_id)
        if account is None:
            raise SourceNotFoundError(f"source {source_id} not found")
        return account, credentials


def _revokable_token(credential: StoredCredential) -> str | None:
    return credential.refresh_token or credential.access_token
