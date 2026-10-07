"""Ports for the embedding stage.

``Embedder`` abstracts the model-serving backend (a local TEI server today);
``EmbeddingRepository`` is the write port for the ``search.chunk`` embedding
columns plus the ``embedding_failure`` / ``embedding_run`` bookkeeping tables.
Both operate on plain ``Vector`` (``list[float]``) — no pgvector or httpx here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from rosalind.domain.search import EmbeddingSpace, Vector

__all__ = [
    "EmbedWorkItem",
    "EmbedWrite",
    "Embedder",
    "EmbeddingError",
    "EmbeddingFailureRow",
    "EmbeddingRepository",
    "EmbeddingRunRow",
    "EmbeddingSpace",
    "TransientEmbeddingError",
    "Vector",
]


class EmbeddingError(Exception):
    """The embedder could not produce a vector for the given input."""


class TransientEmbeddingError(EmbeddingError):
    """A retryable failure (timeout, 429, 5xx) that outlived its retries."""


@dataclass(frozen=True)
class EmbedWorkItem:
    """One chunk that needs a vector for the active space."""

    chunk_id: uuid.UUID
    text: str
    text_sha256: str


@dataclass(frozen=True)
class EmbedWrite:
    """A vector to write, guarded by the text hash it was computed from."""

    chunk_id: uuid.UUID
    vector: Vector
    expected_text_sha256: str


@dataclass(frozen=True)
class EmbeddingFailureRow:
    """One chunk+space that failed to embed, recorded to be skipped until changed."""

    chunk_id: uuid.UUID
    space: str
    text_sha256: str
    error: str
    attempts: int
    last_attempt_at: datetime


@dataclass(frozen=True)
class EmbeddingRunRow:
    """Bookkeeping for one embed run (disclosure ledger input)."""

    space: str
    started_at: datetime
    finished_at: datetime
    host: str
    device_class: str
    dtype: str
    revision: str
    locality: str
    chunks_embedded: int
    chunks_failed: int


class Embedder(Protocol):
    """Produces vectors for the configured space."""

    @property
    def space(self) -> EmbeddingSpace: ...

    @property
    def locality(self) -> str: ...  # 'local' | 'remote'

    @property
    def host(self) -> str: ...

    @property
    def device_class(self) -> str: ...

    def embed_documents(self, texts: list[str]) -> list[Vector]:
        """Embed a batch of texts, returning one vector per text, in order."""

    def embed_query(self, text: str) -> Vector:
        """Embed a single query text (retrieval phase; defined, unused for now)."""


class EmbeddingRepository(Protocol):
    """Write port for embeddings, failure rows, and run rows."""

    def find_embed_work(
        self,
        *,
        space: EmbeddingSpace,
        source_account_id: uuid.UUID,
        embed_quotes: bool,
        embed_trash_spam: bool,
        retry_failed: bool,
        limit: int,
    ) -> list[EmbedWorkItem]:
        """Chunks that need a vector, most recent first."""

    def count_not_embeddable(
        self,
        *,
        source_account_id: uuid.UUID,
        embed_quotes: bool,
        embed_trash_spam: bool,
    ) -> int:
        """Chunks excluded by kind/trash-spam flags (for reporting)."""

    def write_embeddings(
        self, *, space: EmbeddingSpace, writes: Sequence[EmbedWrite]
    ) -> list[uuid.UUID]:
        """Write vectors, guarded by ``chunk.text_sha256 == expected_text_sha256``.

        Returns the chunk ids actually written (guards passed). Failure rows for
        those chunks are cleared in the same transaction.
        """

    def record_failure(self, *, row: EmbeddingFailureRow) -> None:
        """Upsert a failure row keyed by ``(chunk_id, space)``."""

    def record_run(self, *, row: EmbeddingRunRow) -> None:
        """Append one embedding run row."""
