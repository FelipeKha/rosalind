"""Segmentation and cut-plus-marker sanitization.

Segmentation does not need to be perfect: the verifier returns the exact
protected substring inside a segment, so a comma-spliced sentence is still cut
inside the segment. The unit exists to bound verification and to give findings
a stable content hash that quoted copies can share.

Sanitization is deterministic: cut at the protected span and insert one uniform
marker. There is no LLM rewrite. ``index_text`` is the same text without the
marker so searching for the marker itself never matches hidden content.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "MARKER",
    "Redaction",
    "SanitizedText",
    "Segment",
    "Span",
    "merge_spans",
    "normalize_for_hash",
    "sanitize",
    "segment_text",
    "text_hash",
]

MARKER = "[REDACTED BY PRIVACY POLICY]"

# Sentence/clause boundaries: terminal punctuation or a newline, keeping the
# punctuation attached to the preceding segment. This is deliberately modest;
# the verifier's span offsets are what make a cut precise.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")

# Leading quote prefixes ("> ", ">> ", "On ... wrote:") are normalized away for
# hashing so the same sentence quoted in a reply inherits its finding.
_QUOTE_PREFIX = re.compile(r"^\s*(?:>\s*)+", re.MULTILINE)
_WHITESPACE = re.compile(r"\s+")
_LEADING_SEPARATORS = ",;:.!?-–—"


@dataclass(frozen=True, slots=True)
class Span:
    """A half-open character range ``[start, end)`` into a text."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("span start cannot be negative")
        if self.end <= self.start:
            raise ValueError("span end must be greater than start")


@dataclass(frozen=True, slots=True)
class Redaction:
    """Where a marker was inserted in the display text."""

    start: int
    end: int
    type: str = "privacy_policy"


@dataclass(frozen=True, slots=True)
class SanitizedText:
    """The two stored texts plus the marker offsets in ``display_text``."""

    display_text: str
    index_text: str
    redactions: tuple[Redaction, ...]

    @property
    def redacted(self) -> bool:
        return bool(self.redactions)


@dataclass(frozen=True, slots=True)
class Segment:
    """A segment of a field's canonical text."""

    start: int
    end: int
    text: str
    text_hash: str


def normalize_for_hash(text: str) -> str:
    """Normalize text before hashing so quoted/whitespace variants collide."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = _QUOTE_PREFIX.sub("", normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip().casefold()
    return normalized


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


def segment_text(text: str) -> tuple[Segment, ...]:
    """Split ``text`` into sentence/clause segments with exact offsets.

    Every non-whitespace character of the input belongs to exactly one
    segment. Empty/whitespace-only input yields no segments.
    """
    if not text or not text.strip():
        return ()

    segments: list[Segment] = []
    cursor = 0
    for match in _BOUNDARY.finditer(text):
        boundary = match.start()
        if boundary > cursor:
            _append_segment(segments, text, cursor, boundary)
        cursor = match.end()
    if cursor < len(text):
        _append_segment(segments, text, cursor, len(text))
    return tuple(segments)


def _append_segment(segments: list[Segment], text: str, start: int, end: int) -> None:
    raw = text[start:end]
    if not raw.strip():
        return
    # Keep the stored offsets tight to the visible text.
    leading = len(raw) - len(raw.lstrip())
    trailing = len(raw) - len(raw.rstrip())
    tight_start = start + leading
    tight_end = end - trailing
    if tight_end <= tight_start:
        return
    segment = text[tight_start:tight_end]
    segments.append(
        Segment(
            start=tight_start,
            end=tight_end,
            text=segment,
            text_hash=text_hash(segment),
        )
    )


def merge_spans(
    spans: tuple[Span, ...] | list[Span], text_length: int
) -> tuple[Span, ...]:
    """Clamp, snap to word boundaries, and merge overlapping/adjacent spans."""
    clamped: list[Span] = []
    for span in spans:
        start = max(0, min(span.start, text_length))
        end = max(0, min(span.end, text_length))
        if end <= start:
            continue
        clamped.append(Span(start, end))
    if not clamped:
        return ()
    clamped.sort(key=lambda span: (span.start, span.end))
    merged: list[Span] = [clamped[0]]
    for span in clamped[1:]:
        last = merged[-1]
        if span.start <= last.end:
            merged[-1] = Span(last.start, max(last.end, span.end))
        else:
            merged.append(span)
    return tuple(merged)


def sanitize(
    text: str,
    spans: tuple[Span, ...] | list[Span],
    *,
    marker: str = MARKER,
    snap_words: bool = True,
) -> SanitizedText:
    """Cut ``spans`` out of ``text`` and insert one marker per merged span."""
    if not spans:
        return SanitizedText(display_text=text, index_text=text, redactions=())

    prepared = tuple(_snap(span, text) if snap_words else span for span in spans)
    merged = merge_spans(prepared, len(text))
    if not merged:
        return SanitizedText(display_text=text, index_text=text, redactions=())

    display_parts: list[str] = []
    index_parts: list[str] = []
    redactions: list[Redaction] = []
    cursor = 0
    display_offset = 0
    for span in merged:
        display_parts.append(text[cursor : span.start])
        display_offset += len(text[cursor : span.start])
        display_parts.append(marker)
        redactions.append(
            Redaction(
                start=display_offset,
                end=display_offset + len(marker),
            )
        )
        display_offset += len(marker)
        index_parts.append(text[cursor : span.start])
        cursor = span.end
    display_parts.append(text[cursor:])
    index_parts.append(text[cursor:])

    display_text = "".join(display_parts)
    index_text = _clean_index_text("".join(index_parts))
    return SanitizedText(
        display_text=display_text,
        index_text=index_text,
        redactions=tuple(redactions),
    )


def _snap(span: Span, text: str) -> Span:
    """Expand a span to word boundaries so a cut never splits a word."""
    start = span.start
    end = span.end
    while start > 0 and text[start - 1].isalnum() and text[start].isalnum():
        start -= 1
    while end < len(text) and text[end].isalnum() and text[end - 1].isalnum():
        end += 1
    return Span(start, end)


def _clean_index_text(text: str) -> str:
    """Normalize the marker-free text: collapse runs and trim separators."""
    normalized = _WHITESPACE.sub(" ", text).strip()
    return normalized.lstrip(_LEADING_SEPARATORS).strip()
