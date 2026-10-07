"""Persistence for Rosalind accounts and account identities."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence.models.account import (
    Account as AccountModel,
)
from rosalind.adapters.outbound.persistence.models.account import (
    AccountIdentity as AccountIdentityModel,
)
from rosalind.domain.account import Account, AccountIdentity


class PostgresAccountRepository:
    def __init__(self, session: Session):
        self._session = session

    def get(self, account_id: uuid.UUID) -> Account | None:
        model = self._session.get(AccountModel, account_id)
        return self._to_account(model) if model is not None else None

    def set_self_person_id(self, account_id: uuid.UUID, person_id: uuid.UUID) -> None:
        self._session.execute(
            update(AccountModel)
            .where(AccountModel.id == account_id)
            .values(self_person_id=person_id)
        )

    @staticmethod
    def _to_account(model: AccountModel) -> Account:
        return Account(
            id=model.id,
            self_person_id=model.self_person_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class PostgresAccountIdentityRepository:
    def __init__(self, session: Session):
        self._session = session

    def get(self, issuer: str, subject: str) -> AccountIdentity | None:
        model = self._session.scalar(
            select(AccountIdentityModel).where(
                AccountIdentityModel.issuer == issuer,
                AccountIdentityModel.subject == subject,
            )
        )
        return self._to_domain(model) if model is not None else None

    def get_or_create(self, issuer: str, subject: str) -> AccountIdentity:
        existing = self.get(issuer, subject)
        if existing is not None:
            return existing

        account = AccountModel()
        self._session.add(account)
        self._session.flush()

        identity = AccountIdentityModel(
            account_id=account.id, issuer=issuer, subject=subject
        )
        self._session.add(identity)
        self._session.flush()
        return self._to_domain(identity)

    def touch(self, identity_id: uuid.UUID, last_seen_at: datetime) -> None:
        model = self._session.get(AccountIdentityModel, identity_id)
        if model is None:
            return
        model.last_seen_at = last_seen_at

    @staticmethod
    def _to_domain(model: AccountIdentityModel) -> AccountIdentity:
        return AccountIdentity(
            id=model.id,
            account_id=model.account_id,
            issuer=model.issuer,
            subject=model.subject,
            created_at=model.created_at,
            last_seen_at=model.last_seen_at,
        )
