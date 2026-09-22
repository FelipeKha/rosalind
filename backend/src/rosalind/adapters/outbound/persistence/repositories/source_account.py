"""Persistence for source accounts (account-level CRUD only).

OAuth credentials and auth requests remain ORM-internal to ``SourceService``;
this repository only maps ``public.source_account`` rows to and from the domain
``SourceAccount`` entity. Mutations flush but do not commit so they can join a
larger service-level transaction.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence.models.source import (
    SourceAccount as SourceAccountModel,
)
from rosalind.domain.source import SourceAccount


class PostgresSourceAccountRepository:
    def get(self, db: Session, source_id: uuid.UUID) -> SourceAccount | None:
        account = db.get(SourceAccountModel, source_id)
        return self._to_domain(account) if account is not None else None

    def get_by_name(self, db: Session, name: str) -> SourceAccount | None:
        account = db.scalar(
            select(SourceAccountModel).where(SourceAccountModel.name == name)
        )
        return self._to_domain(account) if account is not None else None

    def get_by_identity(
        self, db: Session, provider: str, account_identifier: str
    ) -> SourceAccount | None:
        account = db.scalar(
            select(SourceAccountModel).where(
                SourceAccountModel.provider == provider,
                SourceAccountModel.account_identifier == account_identifier,
            )
        )
        return self._to_domain(account) if account is not None else None

    def list(self, db: Session) -> list[SourceAccount]:
        accounts = db.scalars(
            select(SourceAccountModel).order_by(SourceAccountModel.created_at)
        ).all()
        return [self._to_domain(account) for account in accounts]

    def create(
        self, db: Session, *, provider: str, name: str | None = None
    ) -> SourceAccount:
        account = SourceAccountModel(provider=provider, name=name)
        db.add(account)
        db.flush()
        return self._to_domain(account)

    def update(self, db: Session, account: SourceAccount) -> SourceAccount:
        model = db.get(SourceAccountModel, account.id)
        if model is None:
            raise ValueError(f"source account {account.id} not found")
        model.provider = account.provider
        model.name = account.name
        model.account_identifier = account.account_identifier
        model.display_name = account.display_name
        db.flush()
        return self._to_domain(model)

    def delete(self, db: Session, source_id: uuid.UUID) -> None:
        model = db.get(SourceAccountModel, source_id)
        if model is None:
            return
        db.delete(model)
        db.flush()

    @staticmethod
    def _to_domain(account: SourceAccountModel) -> SourceAccount:
        return SourceAccount(
            id=account.id,
            provider=account.provider,
            name=account.name,
            account_identifier=account.account_identifier,
            display_name=account.display_name,
            created_at=account.created_at,
        )
