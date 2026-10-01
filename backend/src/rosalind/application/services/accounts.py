"""Application service for accounts.

Resolves a validated token identity (``issuer`` + ``subject``) to the Rosalind
``Account`` it belongs to, creating the account and identity on first sight.
This is just-in-time provisioning: the identity provider is authoritative for
credentials, Rosalind only records the mapping.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rosalind.application.errors import AccountNotFoundError
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.account import Account


class AccountService:
    def get_or_create(self, uow: UnitOfWork, issuer: str, subject: str) -> Account:
        identity = uow.account_identities.get_or_create(issuer, subject)
        uow.account_identities.touch(identity.id, datetime.now(UTC))
        account = uow.accounts.get(identity.account_id)
        if account is None:
            raise AccountNotFoundError(f"account {identity.account_id} not found")
        return account
