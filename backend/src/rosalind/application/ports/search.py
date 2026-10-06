"""Ports for the chunk stage.

``ChunkRepository`` is the write port for ``search.chunk`` /
``search.chunk_build``; the concrete implementation lives in
``adapters.outbound.persistence``. ``TokenCounter`` is defined in the domain
(``domain.search``) and re-exported here for convenience.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from rosalind.domain.search import ChunkDraft, TokenCounter

__all__ = [
    "ChunkAttachmentInput",
    "ChunkBuildRow",
    "ChunkRepository",
    "ChunkSegmentInput",
    "ChunkWorkItem",
    "ChunkWriteResult",
    "TokenCounter",
]


@dataclass(frozen=True)
class ChunkSegmentInput:
    """One segment of an email's clean text (kind + offsets into clean_text)."""

    kind: str
    start_offset: int
    end_offset: int
    language: str | None
    covered_by_email_id: uuid.UUID | None
    quoted_author: str | None


@dataclass(frozen=True)
class ChunkAttachmentInput:
    """One non-inline attachment with its extracted text (if any)."""

    attachment_id: uuid.UUID
    filename: str | None
    text: str | None
    truncated: bool
    language: str | None
    stage_version: str | None
    text_sha256: str | None
    text_ready: bool

    @property
    def source_digest(self) -> str | None:
        """The digest the work finder compares against ``chunk_build``."""
        if self.stage_version is None or self.text_sha256 is None:
            return None
        return f"{self.stage_version}:{self.text_sha256}"


@dataclass(frozen=True)
class ChunkWorkItem:
    """All inputs the chunker needs for one email."""

    email_id: uuid.UUID
    thread_id: uuid.UUID | None
    source_account_id: uuid.UUID
    source_account_num: int
    sent_at: datetime
    sender_handle: str
    sender_display: str
    recipient_handles: tuple[str, ...]
    recipient_display: tuple[str, ...]
    participant_handles: tuple[str, ...]
    direction: str
    has_attachment: bool
    is_trash_or_spam: bool
    tags: tuple[str, ...]
    subject: str | None
    clean_text: str | None
    text_status: str
    segments_digest: str | None
    segments: tuple[ChunkSegmentInput, ...]
    attachments: tuple[ChunkAttachmentInput, ...]


@dataclass(frozen=True)
class ChunkBuildRow:
    """One ``search.chunk_build`` row written alongside a kind's chunks."""

    chunk_kind: str
    attachment_id: uuid.UUID | None
    index_version: str
    source_digest: str | None
    built_at: datetime
    chunk_count: int
    status: str
    error: str | None


@dataclass(frozen=True)
class ChunkWriteResult:
    written: int
    unchanged: int


class ChunkRepository(Protocol):
    """Write port for search chunks and their build bookkeeping."""

    def list_stale_email_ids(
        self,
        *,
        source_account_id: uuid.UUID,
        index_version: str,
        limit: int,
    ) -> list[uuid.UUID]:
        """Email ids whose chunk rows are missing or stale for at least one
        ready source (body/quote text ready, or an attachment with done text)."""

    def load_chunk_inputs(
        self, *, email_ids: Sequence[uuid.UUID]
    ) -> list[ChunkWorkItem]:
        """Fetch the full chunk inputs for the given emails."""

    def replace_chunks(
        self,
        *,
        email_id: uuid.UUID,
        drafts: Sequence[ChunkDraft],
        builds: Sequence[ChunkBuildRow],
    ) -> ChunkWriteResult:
        """Replace an email's chunks and build rows in place (idempotent).

        Upserts each draft by deterministic id with an only-if-changed guard,
        deletes chunks whose seq is past the new count, and writes the build
        rows. Returns how many chunks were written vs left unchanged.
        """
