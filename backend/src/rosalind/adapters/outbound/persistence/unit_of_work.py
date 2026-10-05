"""SQLAlchemy-backed unit of work.

Binds a single ``Session`` to every repository so the application layer can
coordinate one transaction across repositories without importing SQLAlchemy.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence.repositories.account import (
    PostgresAccountIdentityRepository,
    PostgresAccountRepository,
)
from rosalind.adapters.outbound.persistence.repositories.email_canonical import (
    PostgresEmailCanonicalRepository,
)
from rosalind.adapters.outbound.persistence.repositories.imports import (
    PostgresImportRepository,
)
from rosalind.adapters.outbound.persistence.repositories.oauth import (
    PostgresOAuthAuthRequestRepository,
    PostgresOAuthCredentialRepository,
)
from rosalind.adapters.outbound.persistence.repositories.person_canonical import (
    PostgresPersonCanonicalRepository,
)
from rosalind.adapters.outbound.persistence.repositories.source_account import (
    PostgresSourceAccountRepository,
)
from rosalind.adapters.outbound.persistence.repositories.source_record import (
    PostgresSourceRecordRepository,
)
from rosalind.application.ports.repositories import (
    AccountIdentityRepository,
    AccountRepository,
    EmailCanonicalRepository,
    ImportRepository,
    OAuthAuthRequestRepository,
    OAuthCredentialRepository,
    PersonCanonicalRepository,
    SourceAccountRepository,
    SourceRecordRepository,
)


class SqlAlchemyUnitOfWork:
    """Session-bound repositories plus explicit transaction control."""

    accounts: AccountRepository
    account_identities: AccountIdentityRepository
    source_accounts: SourceAccountRepository
    source_records: SourceRecordRepository
    credentials: OAuthCredentialRepository
    auth_requests: OAuthAuthRequestRepository
    imports: ImportRepository
    person_canonical: PersonCanonicalRepository
    email_canonical: EmailCanonicalRepository

    def __init__(self, session: Session):
        self._session = session
        self.accounts = PostgresAccountRepository(session)
        self.account_identities = PostgresAccountIdentityRepository(session)
        self.source_accounts = PostgresSourceAccountRepository(session)
        self.source_records = PostgresSourceRecordRepository(session)
        self.credentials = PostgresOAuthCredentialRepository(session)
        self.auth_requests = PostgresOAuthAuthRequestRepository(session)
        self.imports = PostgresImportRepository(session)
        self.person_canonical = PostgresPersonCanonicalRepository(session)
        self.email_canonical = PostgresEmailCanonicalRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def flush(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self._session.rollback()
        self._session.close()
