"""Derived email text and segment value objects for the enrich stage.

These are the *derived* read models the enrich stage writes into the ``derived``
schema. They are rebuildable from ``core.email_message`` by definition, so they
carry no provenance of their own — the evidence stays in ``core`` and ``raw``.

Offsets are code-point offsets into ``clean_text`` exactly as stored: Postgres
``substr`` and Python slicing both index code points, so a segment's text is
always ``clean_text[start_offset:end_offset]``. Segmentation is lossless — the
segments tile ``clean_text`` with no gaps or overlaps.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum


class SegmentKind(StrEnum):
    """The role a contiguous span of message text plays."""

    NEW = "new"
    QUOTED = "quoted"
    FORWARDED = "forwarded"
    SIGNATURE = "signature"
    # Reserved: disclaimer detection is deferred (text-pattern based and
    # language-specific); such spans are currently emitted as ``new``.
    DISCLAIMER = "disclaimer"


class CleanMethod(StrEnum):
    """Which body representation ``clean_text`` was derived from."""

    PLAIN = "plain"
    HTML = "html"


def content_sha256(text_plain: str | None, text_html: str | None) -> str:
    """Deterministic hash over a message's body representations.

    Length prefixes make the boundary between ``text_plain`` and ``text_html``
    unambiguous, so a message whose parts shift bytes cannot collide. ``None``
    and ``""`` are treated as identical (the enrich stage sees both as "no
    usable text"), which avoids spurious reprocessing when a part appears or
    disappears.
    """
    digest = hashlib.sha256()
    for value in (text_plain or "", text_html or ""):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def segments_digest(
    stage_version: str,
    input_sha256: str | None,
    segments: tuple[EmailSegment, ...],
) -> str | None:
    """Deterministic hash over the segmentation inputs and coverage state.

    Captures the stage version, the input hash, and each segment's kind,
    offsets, and coverage so a change to any of them (including 4C marking a
    quote as covered) invalidates the chunk source digest. Returns ``None``
    when there are no segments (nothing to tile).
    """
    if not segments:
        return None
    digest = hashlib.sha256()
    for value in (stage_version, input_sha256 or ""):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    for segment in segments:
        for value in (
            segment.kind.value,
            str(segment.start_offset),
            str(segment.end_offset),
            str(segment.covered_by_email_id or ""),
        ):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def text_sha256(text: str | None) -> str | None:
    """SHA-256 of extracted attachment text; lets a rebuild reuse embeddings."""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EmailSegment:
    """One span of ``clean_text`` classified into a ``SegmentKind``.

    ``language``/``language_confidence`` are ``None`` until the language
    detector annotates the segment; they are filled with ``dataclasses.replace``
    so segmentation itself stays pure and side-effect free.
    """

    seq: int
    kind: SegmentKind
    start_offset: int
    end_offset: int
    quote_depth: int = 0
    attribution_raw: str | None = None
    quoted_author: str | None = None
    quoted_at: str | None = None
    language: str | None = None
    language_confidence: float | None = None
    # Set by the (deferred) 4C coverage pass; included in ``segments_digest`` so
    # a later coverage change invalidates the chunk source digest.
    covered_by_email_id: str | None = None

    def text(self, clean_text: str) -> str:
        return clean_text[self.start_offset : self.end_offset]


@dataclass(frozen=True)
class EmailText:
    """Derived clean text plus its tiling segments for one email message."""

    clean_text: str
    clean_method: CleanMethod
    segments: tuple[EmailSegment, ...]


class AttachmentStatus(StrEnum):
    DONE = "done"
    EMPTY = "empty"
    NEEDS_OCR = "needs_ocr"
    UNSUPPORTED = "unsupported"
    TOO_LARGE = "too_large"
    ENCRYPTED = "encrypted"
    FAILED = "failed"


@dataclass(frozen=True)
class AttachmentText:
    """Derived text extracted from one content-addressed attachment blob."""

    blob_sha256: str
    status: AttachmentStatus
    text: str | None = None
    method: str | None = None
    page_count: int | None = None
    language: str | None = None
    error: str | None = None
    truncated: bool = False
    text_sha256: str | None = None
