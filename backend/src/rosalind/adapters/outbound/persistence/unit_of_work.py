"""SQLAlchemy-backed unit of work.

Binds a single ``Session`` to every repository so the application layer can
coordinate one transaction across repositories without importing SQLAlchemy.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session

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
    ImportRepository,
    OAuthAuthRequestRepository,
    OAuthCredentialRepository,
    PersonCanonicalRepository,
    SourceAccountRepository,
    SourceRecordRepository,
)


class SqlAlchemyUnitOfWork:
    """Session-bound repositories plus explicit transaction control."""

    source_accounts: SourceAccountRepository
    source_records: SourceRecordRepository
    credentials: OAuthCredentialRepository
    auth_requests: OAuthAuthRequestRepository
    imports: ImportRepository
    person_canonical: PersonCanonicalRepository

    def __init__(self, session: Session):
        self._session = session
        self.source_accounts = PostgresSourceAccountRepository(session)
        self.source_records = PostgresSourceRecordRepository(session)
        self.credentials = PostgresOAuthCredentialRepository(session)
        self.auth_requests = PostgresOAuthAuthRequestRepository(session)
        self.imports = PostgresImportRepository(session)
        self.person_canonical = PostgresPersonCanonicalRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def flush(self) -> None:
        self._session.flush()

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
