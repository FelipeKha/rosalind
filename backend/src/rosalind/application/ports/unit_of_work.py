"""Transactional unit-of-work port.

A ``UnitOfWork`` coordinates a single database transaction across the
repositories that participate in a write use case. It is only needed by
services that must commit (or roll back) several repositories together
(e.g. canonicalization); read-only services depend on their repository port
directly instead of on this fat interface.

The concrete implementation lives in ``adapters.outbound.persistence`` and owns
the underlying connection/session lifecycle.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from rosalind.application.ports.repositories import (
    ImportRepository,
    OAuthAuthRequestRepository,
    OAuthCredentialRepository,
    PersonCanonicalRepository,
    SourceAccountRepository,
    SourceRecordRepository,
)


class UnitOfWork(Protocol):
    """Bundles the repositories of one transaction and its commit/flush control."""

    source_accounts: SourceAccountRepository
    source_records: SourceRecordRepository
    credentials: OAuthCredentialRepository
    auth_requests: OAuthAuthRequestRepository
    imports: ImportRepository
    person_canonical: PersonCanonicalRepository

    def commit(self) -> None: ...

    def flush(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
