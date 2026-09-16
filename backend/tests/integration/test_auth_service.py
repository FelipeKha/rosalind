from datetime import UTC, datetime, timedelta

from google.oauth2.credentials import Credentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind import models
from rosalind.auth import service as auth_service

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _credentials(expiry: datetime) -> Credentials:
    return Credentials(
        token="access-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=SCOPES,
        expiry=expiry,
    )


def _create_account_with_credentials(
    db: Session, expiry: datetime
) -> models.SourceAccount:
    account = models.SourceAccount(provider="google", account_identifier="12345")
    db.add(account)
    db.flush()
    auth_service._upsert_credential(account, _credentials(expiry), provider="google")
    db.commit()
    return account


def test_load_credentials_roundtrips_stored_tokens(db_session: Session) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    _create_account_with_credentials(db_session, future)

    account, credentials = auth_service.load_credentials(db_session, "google")

    assert account.account_identifier == "12345"
    assert credentials.token == "access-token"
    assert credentials.refresh_token == "refresh-token"


def test_load_credentials_refreshes_expired_token(
    db_session: Session, monkeypatch
) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    _create_account_with_credentials(db_session, past)

    def fake_refresh(credentials: Credentials) -> Credentials:
        credentials.token = "refreshed-access-token"
        credentials.expiry = datetime.now(UTC) + timedelta(hours=1)
        return credentials

    monkeypatch.setattr(auth_service.google_auth, "refresh", fake_refresh)

    _, credentials = auth_service.load_credentials(db_session, "google")

    assert credentials.token == "refreshed-access-token"


def test_disconnect_removes_credentials_keeps_account(
    db_session: Session, monkeypatch
) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    account = _create_account_with_credentials(db_session, future)
    revoked: list[str] = []
    monkeypatch.setattr(
        auth_service.google_auth, "revoke", lambda token: revoked.append(token)
    )

    result = auth_service.disconnect(db_session, "google")

    assert result.status == "disconnected"
    assert result.revoked is True
    assert revoked == ["refresh-token"]
    assert db_session.get(models.SourceAccount, account.id) is not None
    assert db_session.scalars(select(models.OAuthCredential)).all() == []
