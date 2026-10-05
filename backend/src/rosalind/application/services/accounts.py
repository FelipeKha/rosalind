"""Application service for accounts.

Resolves a validated token identity (``issuer`` + ``subject``) to the Rosalind
``Account`` it belongs to, creating the account and identity on first sight.
This is just-in-time provisioning: the identity provider is authoritative for
credentials, Rosalind only records the mapping.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from rosalind.application.errors import AccountNotFoundError, SelfPersonError
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

    def set_self_person(
        self, uow: UnitOfWork, account_id: uuid.UUID, person_id: uuid.UUID
    ) -> Account:
        """Link the account to its canonical self person.

        The person is set explicitly and must already have at least one
        ``core.person_email``, because that email is what the email pipeline
        uses to compute a message's direction.
        """
        if not uow.person_canonical.has_email(person_id):
            raise SelfPersonError(
                f"person {person_id} has no email; import a contact with an "
                "email address before linking it as the self person"
            )
        uow.accounts.set_self_person_id(account_id, person_id)
        uow.commit()
        account = uow.accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(f"account {account_id} not found")
        return account
