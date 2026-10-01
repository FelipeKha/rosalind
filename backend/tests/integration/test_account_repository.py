"""Integration tests for account and account-identity persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork


def test_get_or_create_is_idempotent(db_session: Session) -> None:
    uow = SqlAlchemyUnitOfWork(db_session)
    issuer = "http://localhost:8080/realms/rosalind"
    subject = "user-123"

    first = uow.account_identities.get_or_create(issuer, subject)
    uow.commit()

    second = uow.account_identities.get_or_create(issuer, subject)

    assert first.id == second.id
    assert first.account_id == second.account_id

    count = db_session.scalar(
        select(models.AccountIdentity).where(
            models.AccountIdentity.issuer == issuer,
            models.AccountIdentity.subject == subject,
        )
    )
    assert count is not None

    identities = db_session.scalars(
        select(models.AccountIdentity).where(
            models.AccountIdentity.issuer == issuer,
            models.AccountIdentity.subject == subject,
        )
    ).all()
    assert len(identities) == 1


def test_distinct_subjects_create_distinct_accounts(db_session: Session) -> None:
    uow = SqlAlchemyUnitOfWork(db_session)
    issuer = "http://localhost:8080/realms/rosalind"

    first = uow.account_identities.get_or_create(issuer, "user-1")
    second = uow.account_identities.get_or_create(issuer, "user-2")

    assert first.account_id != second.account_id


def test_account_is_created_with_identity(db_session: Session) -> None:
    uow = SqlAlchemyUnitOfWork(db_session)
    issuer = "http://localhost:8080/realms/rosalind"

    identity = uow.account_identities.get_or_create(issuer, "user-9")
    uow.commit()

    account = uow.accounts.get(identity.account_id)
    assert account is not None
    assert account.self_person_id is None
