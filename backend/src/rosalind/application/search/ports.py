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
    SearchPlan,
)
from rosalind.application.search.rerank import ChunkText, RerankTextMode
from rosalind.application.search.retrieve import LexicalResult
from rosalind.application.search.semantic import SemanticResult

__all__ = [
    "AuditEvent",
    "AuditPort",
    "ChunkTextPort",
    "CursorCodecPort",
    "CursorDecodeError",
    "EmbedderPort",
    "EntityResolverPort",
    "LexicalRetrieverPort",
    "RerankConfig",
    "RerankTextMode",
    "RerankerPort",
    "SearchConfig",
    "SearchMetadata",
    "SearchMetadataPort",
    "SearchScopePort",
    "SemanticRetrieverPort",
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
class RerankConfig:
    """Rerank settings. Configuration, never agent input.

    ``deadline_ms`` bounds the whole step; ``timeout_ms`` bounds a single
    request. ``max_input_tokens`` is shared by the query, the passage, and the
    cross-encoder's special tokens, so the orchestrator subtracts the query's
    token count before deciding how much passage may remain.
    """

    max_input_tokens: int
    text_mode: RerankTextMode = RerankTextMode.INDEX
    max_batch_size: int = 32
    concurrency: int = 1
    retries: int = 1
    timeout_ms: int = 20000
    deadline_ms: int = 8000

    def __post_init__(self) -> None:
        if self.max_input_tokens < 1:
            raise ValueError("max_input_tokens must be positive")
        if self.max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")
        if self.concurrency < 1:
            raise ValueError("concurrency must be positive")
        if self.retries < 0:
            raise ValueError("retries cannot be negative")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        if self.deadline_ms <= 0:
            raise ValueError("deadline_ms must be positive")


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


class LexicalRetrieverPort(Protocol):
    async def retrieve(self, plan: SearchPlan) -> LexicalResult:
        """Run filtered BM25 retrieval for a plan (online search step 2.1).

        Returns up to ``plan.budgets.lexical_k`` ranked chunks with the engine's
        BM25 score preserved, an ``exhausted`` flag that is only true when the
        whole candidate stream was scanned, and a ``filter_path`` describing how
        filters were applied. Must always apply ``plan.scope``, never widen it.
        """


class SemanticRetrieverPort(Protocol):
    async def retrieve(self, plan: SearchPlan) -> SemanticResult:
        """Run filtered vector retrieval for a plan (online search step 2.2).

        Returns up to ``plan.budgets.semantic_k`` ranked chunks with the engine's
        cosine distance preserved, a ``complete`` flag that is only true when
        every matching chunk was considered, and the ``filter_path`` describing
        how the search was executed (``exact`` or ``ann_iterative``). Must always
        apply ``plan.scope``, never widen it, and must only consider chunks whose
        stored embedding is fresh (its companion text hash equals ``text_sha256``).
        """


class RerankerPort(Protocol):
    async def rerank(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        """Score each passage against the query, returning raw scores in input order.

        Higher is better. Raises ``RerankBackendError`` for a transient failure
        that outlived retries and ``RerankError`` for a malformed response.
        """


class ChunkTextPort(Protocol):
    async def get_rerank_texts(
        self, chunk_ids: tuple[uuid.UUID, ...], mode: RerankTextMode
    ) -> tuple[ChunkText, ...]:
        """Return text for each id in requested order; ids absent from the store
        are dropped (not an error). A database failure raises ``RerankError``."""


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
