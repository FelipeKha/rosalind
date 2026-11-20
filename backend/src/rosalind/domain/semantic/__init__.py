"""Pure semantic-enforcement text primitives.

No SQLAlchemy, FastAPI, provider SDKs or settings. Segmentation, content
hashing and cut-plus-marker sanitization live here so the offline builder, the
online path and tests share one implementation.
"""

from rosalind.domain.semantic.text import (
    MARKER,
    Redaction,
    SanitizedText,
    Segment,
    Span,
    merge_spans,
    normalize_for_hash,
    sanitize,
    segment_text,
    text_hash,
)

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
