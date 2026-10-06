"""Ports for the Prepare step of the online search pipeline.

Prepare depends only on these Protocols (plus the plan value objects), so it
never imports SQLAlchemy, pgvector, ParadeDB, httpx, or the embedding
implementation. The concrete implementations live in ``adapters.outbound``.

The security-critical contract is explicit scope propagation: the entity and
thread resolvers take the *effective* ``Scope`` (``account_id`` + the narrowed
``source_account_ids``), never a bare ``account_id``, so an adapter cannot
resolve a handle or thread outside what the caller may see.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from rosalind.application.search.plan import (
    Budgets,
    Cursor,
    FusionConfig,
    PlanWarning,
    PrepareTimings,
    QueryVector,
    ResolvedEntity,
    Scope,
)

__all__ = [
    "AuditEvent",
    "AuditPort",
    "CursorCodecPort",
    "CursorDecodeError",
    "EmbedderPort",
    "EntityResolverPort",
    "SearchConfig",
    "SearchMetadata",
    "SearchMetadataPort",
    "SearchScopePort",
    "ThreadResolverPort",
]


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """Configuration Prepare reads but the agent never controls.

    ``index_version``, budgets, fusion settings, and embedding model/version all
    participate in the search-plan fingerprint, so they must come from
    configuration, never from the request.
    """

    index_version: str
    embedding_model: str | None
    embedding_version: str | None
    reranker: str | None

    budgets: Budgets
    fusion: FusionConfig

    max_query_chars: int
    max_list_values: int
    default_timezone: str


@dataclass(frozen=True, slots=True)
class SearchMetadata:
    """Corpus facts used for short-circuit and tag/language/handle validation."""

    min_sent_at: datetime | None
    max_sent_at: datetime | None
    known_tags: frozenset[str]
    known_languages: frozenset[str]
    known_handles: frozenset[str]


class SearchScopePort(Protocol):
    async def get_scope(self, account_id: uuid.UUID) -> frozenset[uuid.UUID]:
        """The source accounts this account may search (the authorized set)."""


class SearchMetadataPort(Protocol):
    async def get_metadata(
        self, source_account_ids: frozenset[uuid.UUID]
    ) -> SearchMetadata:
        """Date coverage and the tag/language vocabulary for the given scope."""


class EntityResolverPort(Protocol):
    async def resolve(
        self,
        scope: Scope,
        values: tuple[str, ...],
    ) -> tuple[ResolvedEntity, ...]:
        """Expand person references ("me", entity UUIDs, addresses) to handles.

        Must return handles restricted to ``scope``: an entity is only expanded
        to the email addresses it holds within ``scope.source_account_ids``.
        """


class ThreadResolverPort(Protocol):
    async def resolve_thread(
        self,
        scope: Scope,
        message_id: uuid.UUID,
    ) -> uuid.UUID | None:
        """The current thread of a message within ``scope``, or ``None``.

        Must never resolve a message outside ``scope.source_account_ids``.
        """


class EmbedderPort(Protocol):
    async def embed(self, text: str, model: str, version: str) -> QueryVector:
        """Embed a query text for semantic retrieval."""


class CursorDecodeError(Exception):
    """A paging token could not be decoded or does not match the request."""


class CursorCodecPort(Protocol):
    def decode(
        self,
        token: str,
        *,
        account_id: uuid.UUID,
        index_version: str,
    ) -> Cursor:
        """Decode and verify a paging token (signature, account, index version)."""

    def encode(
        self,
        cursor: Cursor,
        *,
        account_id: uuid.UUID,
        index_version: str,
    ) -> str:
        """Encode a paging token for the given account and index version."""


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """What Prepare records about one call, once the outcome is known.

    Deliberately excludes the query vector (only its absence is implicit); the
    plan fingerprint and metadata are enough to replay evaluation.
    """

    request_id: uuid.UUID
    audit_id: uuid.UUID
    account_id: uuid.UUID
    client_id: str
    source_account_ids: frozenset[uuid.UUID]
    fingerprint: str | None
    mode_requested: str | None
    mode_effective: str | None
    index_version: str
    embedding_model: str | None
    embedding_version: str | None
    warnings: tuple[PlanWarning, ...]
    short_circuit_reason: str | None
    timings: PrepareTimings | None


class AuditPort(Protocol):
    async def record(self, event: AuditEvent) -> None:
        """Record one Prepare outcome (logs today; a durable table later)."""
