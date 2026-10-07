"""Provider-independent email value objects and normalization rules."""

from rosalind.domain.email.canonical import (
    CanonicalAttachment,
    CanonicalEmail,
    CanonicalObservation,
    CanonicalParticipant,
    CanonicalThread,
    message_uuid,
)
from rosalind.domain.email.enrichment import (
    AttachmentStatus,
    AttachmentText,
    CleanMethod,
    EmailSegment,
    EmailText,
    SegmentKind,
    content_sha256,
    segments_digest,
    text_sha256,
)
from rosalind.domain.email.message_id import normalize_message_id, parse_message_ids
from rosalind.domain.email.observations import (
    EmailAddress,
    EmailAttachment,
    ParsedEmail,
    ParseWarning,
)
from rosalind.domain.email.threading import ThreadEdge, compute_thread_roots

__all__ = [
    "AttachmentStatus",
    "AttachmentText",
    "CanonicalAttachment",
    "CanonicalEmail",
    "CanonicalObservation",
    "CanonicalParticipant",
    "CanonicalThread",
    "CleanMethod",
    "EmailAddress",
    "EmailAttachment",
    "EmailSegment",
    "EmailText",
    "ParseWarning",
    "ParsedEmail",
    "SegmentKind",
    "ThreadEdge",
    "compute_thread_roots",
    "content_sha256",
    "message_uuid",
    "normalize_message_id",
    "parse_message_ids",
    "segments_digest",
    "text_sha256",
]
