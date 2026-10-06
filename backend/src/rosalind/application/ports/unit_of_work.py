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

from rosalind.application.ports.embedding import EmbeddingRepository
from rosalind.application.ports.repositories import (
    AccountIdentityRepository,
    AccountRepository,
    AttachmentTextRepository,
    EmailCanonicalRepository,
    EmailEnrichmentRepository,
    ImportRepository,
    OAuthAuthRequestRepository,
    OAuthCredentialRepository,
    PersonCanonicalRepository,
    SourceAccountRepository,
    SourceRecordRepository,
)
from rosalind.application.ports.search import ChunkRepository


class UnitOfWork(Protocol):
    """Bundles the repositories of one transaction and its commit/flush control."""

    accounts: AccountRepository
    account_identities: AccountIdentityRepository
    source_accounts: SourceAccountRepository
    source_records: SourceRecordRepository
    credentials: OAuthCredentialRepository
    auth_requests: OAuthAuthRequestRepository
    imports: ImportRepository
    person_canonical: PersonCanonicalRepository
    email_canonical: EmailCanonicalRepository
    email_enrichment: EmailEnrichmentRepository
    attachment_text: AttachmentTextRepository
    chunks: ChunkRepository
    embeddings: EmbeddingRepository

    def commit(self) -> None: ...

    def flush(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
