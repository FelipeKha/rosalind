"""Shared helpers for account-scoped test data.

Every resource is now scoped to a Rosalind account. Tests that write data
through the API (whose ``get_current_account`` is overridden to a stable
account) and tests that write directly through the unit of work must agree on
one account so that account-scoped reads find the data. ``ensure_account``
get-or-creates that account (idempotently) and returns it.
"""

from __future__ import annotations

from rosalind.adapters import composition
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.account import Account

TEST_ISSUER = "http://test/realms/rosalind"
TEST_SUBJECT = "test-subject"


def ensure_account(uow: UnitOfWork) -> Account:
    account = composition.account_service.get_or_create(uow, TEST_ISSUER, TEST_SUBJECT)
    uow.commit()
    return account
