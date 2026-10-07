"""Search-chunk value objects and versioning.

A chunk is the unit of retrieval: a passage of email body, quoted history, or
attachment text, prefixed with context so it reads standalone, and carrying
denormalized filter columns. These value objects are pure — no SQLAlchemy, no
I/O — and are what the chunking service builds and the ``ChunkRepository``
persists.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# A fixed, Rosalind-specific namespace for deterministic chunk UUIDs. Must
# never change, or previously-built chunk ids (and any stored embeddings that
# reference them) would drift.
CHUNK_NAMESPACE = uuid.UUID("1b4e28ba-2fa1-4d63-b3f0-8a3c4b8e9f01")

# Manual versions of the chunker and prefix templates. Bump these when the
# corresponding pure logic changes; they feed ``index_version()`` so a bump
# invalidates every chunk through the work finder.
CHUNKER_VERSION = "chunker/1"
PREFIX_VERSION = "prefix/1"


class ChunkKind(StrEnum):
    """The source a chunk is cut from."""

    EMAIL_BODY = "email_body"
    EMAIL_QUOTE = "email_quote"
    ATTACHMENT = "attachment"

    @property
    def embeddable(self) -> bool:
        """Whether this kind is embedded by default (phase 6).

        Quoted history is lexical-only by default — the largest CPU saving — and
        is only embedded when the ``embed_quotes`` config flag is enabled.
        """
        return self is not ChunkKind.EMAIL_QUOTE


@dataclass(frozen=True)
class ChunkingParams:
    """Token budgets and caps for the chunker (provisional until 0.b/0.c)."""

    target_tokens: int
    max_tokens: int
    overlap_tokens: int
    min_tail_tokens: int
    max_quote_tokens_per_email: int
    max_chunks_per_attachment: int
    include_signature: bool = True


@dataclass(frozen=True)
class ChunkSpan:
    """A chunk as code-point offsets into its source text.

    ``start``/``end`` delimit the chunk text *including* any overlap prefix.
    The non-overlap ("own") content of chunk ``i`` is
    ``text[(spans[i - 1].end if i else start) : end]``, so concatenating the own
    content of every span reproduces the source text exactly — this is what makes
    "no text loss when overlap is removed" testable.
    """

    seq: int
    start: int
    end: int


@dataclass(frozen=True)
class ChunkDraft:
    """One fully-formed chunk ready to persist.

    ``id`` is deterministic (uuid5 over email/kind/attachment/seq) so an
    idempotent upsert can reuse an existing row and, later, its embedding.
    """

    id: uuid.UUID
    email_id: uuid.UUID
    attachment_id: uuid.UUID | None
    thread_id: uuid.UUID | None
    kind: ChunkKind
    seq: int
    text_for_display: str
    text_for_index: str
    text_sha256: str
    language: str | None
    index_version: str
    source_account_id: uuid.UUID
    source_account_num: int
    sent_at: datetime
    sender_handle: str
    recipient_handles: tuple[str, ...]
    participant_handles: tuple[str, ...]
    direction: str
    has_attachment: bool
    is_trash_or_spam: bool
    tags: tuple[str, ...]
    meta: dict = field(default_factory=dict)


def chunk_id(
    email_id: uuid.UUID,
    kind: ChunkKind,
    attachment_id: uuid.UUID | None,
    seq: int,
) -> uuid.UUID:
    """Deterministic chunk id from its uniqueness key."""
    return uuid.uuid5(
        CHUNK_NAMESPACE,
        f"{email_id}:{kind.value}:{attachment_id or ''}:{seq}",
    )


def params_digest(params: ChunkingParams) -> str:
    """Deterministic hash over the chunking parameters."""
    digest = hashlib.sha256()
    for name in (
        "target_tokens",
        "max_tokens",
        "overlap_tokens",
        "min_tail_tokens",
        "max_quote_tokens_per_email",
        "max_chunks_per_attachment",
        "include_signature",
    ):
        value = str(getattr(params, name))
        digest.update(len(value.encode("utf-8")).to_bytes(8, "big"))
        digest.update(value.encode("utf-8"))
    return digest.hexdigest()


def index_version(counter_version: str, params: ChunkingParams) -> str:
    """The chunk index version: chunker + prefix + tokenizer + params.

    A change to any component invalidates every chunk through the work finder.
    """
    return (
        f"{CHUNKER_VERSION}+{PREFIX_VERSION}+{counter_version}+{params_digest(params)}"
    )
