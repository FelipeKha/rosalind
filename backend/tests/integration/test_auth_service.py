from datetime import UTC, datetime, timedelta

from google.oauth2.credentials import Credentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind import models
from rosalind.services import sources as source_service

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
    source_service._upsert_credential(account, _credentials(expiry), provider="google")
    db.commit()
    return account


def test_load_credentials_roundtrips_stored_tokens(db_session: Session) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    account = _create_account_with_credentials(db_session, future)

    loaded_account, credentials = source_service.load_credentials(
        db_session, account.id
    )

    assert loaded_account.account_identifier == "12345"
    assert credentials.token == "access-token"
    assert credentials.refresh_token == "refresh-token"


def test_load_credentials_refreshes_expired_token(
    db_session: Session, monkeypatch
) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    account = _create_account_with_credentials(db_session, past)

    def fake_refresh(credentials: Credentials) -> Credentials:
        credentials.token = "refreshed-access-token"
        credentials.expiry = datetime.now(UTC) + timedelta(hours=1)
        return credentials

    monkeypatch.setattr(source_service.google_auth, "refresh", fake_refresh)

    _, credentials = source_service.load_credentials(db_session, account.id)

    assert credentials.token == "refreshed-access-token"


def test_disconnect_removes_credentials_keeps_account(
    db_session: Session, monkeypatch
) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    account = _create_account_with_credentials(db_session, future)
    revoked: list[str] = []
    monkeypatch.setattr(
        source_service.google_auth, "revoke", lambda token: revoked.append(token)
    )

    result = source_service.disconnect(db_session, account.id)

    assert result.status == "disconnected"
    assert result.revoked is True
    assert revoked == ["refresh-token"]
    assert db_session.get(models.SourceAccount, account.id) is not None
    assert db_session.scalars(select(models.OAuthCredential)).all() == []


def _stub_oauth(monkeypatch, identifier: str = "12345", name: str = "Jane Doe") -> None:
    monkeypatch.setattr(
        source_service.google_auth,
        "build_authorization_url",
        lambda state: ("https://accounts.google.com/auth", "code-verifier"),
    )
    monkeypatch.setattr(
        source_service.google_auth,
        "exchange_code",
        lambda state, code, code_verifier: _credentials(
            datetime.now(UTC) + timedelta(hours=1)
        ),
    )
    monkeypatch.setattr(
        source_service.google_auth,
        "fetch_userinfo",
        lambda credentials: {"id": identifier, "name": name},
    )


def _complete(db: Session) -> models.SourceAccount:
    start = source_service.start_connect(db, "google")
    return source_service.complete_connect(db, start.state, "auth-code")


def test_complete_connect_reuses_existing_account(
    db_session: Session, monkeypatch
) -> None:
    existing = models.SourceAccount(provider="google", account_identifier="12345")
    db_session.add(existing)
    db_session.commit()

    _stub_oauth(monkeypatch)

    account = _complete(db_session)

    assert account.id == existing.id
    assert account.display_name == "Jane Doe"

    google_accounts = db_session.scalars(
        select(models.SourceAccount).where(models.SourceAccount.provider == "google")
    ).all()
    assert len(google_accounts) == 1
    assert google_accounts[0].account_identifier == "12345"
    assert db_session.scalars(select(models.OAuthCredential)).all()


def test_complete_connect_creates_account_when_none_exists(
    db_session: Session, monkeypatch
) -> None:
    _stub_oauth(monkeypatch)

    account = _complete(db_session)

    assert account.account_identifier == "12345"
    assert account.display_name == "Jane Doe"
    assert account.name == "google-personal"
    assert db_session.scalars(select(models.OAuthCredential)).all()


def test_disconnect_then_reconnect_reuses_account(
    db_session: Session, monkeypatch
) -> None:
    _stub_oauth(monkeypatch)
    monkeypatch.setattr(source_service.google_auth, "revoke", lambda token: None)

    first = _complete(db_session)
    first_id = first.id

    result = source_service.disconnect(db_session, first_id)
    assert result.status == "disconnected"
    assert db_session.get(models.SourceAccount, first_id) is not None
    assert db_session.scalars(select(models.OAuthCredential)).all() == []

    second = _complete(db_session)

    assert second.id == first_id
    google_accounts = db_session.scalars(
        select(models.SourceAccount).where(models.SourceAccount.provider == "google")
    ).all()
    assert len(google_accounts) == 1
    assert len(db_session.scalars(select(models.OAuthCredential)).all()) == 1
