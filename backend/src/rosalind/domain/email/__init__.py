"""Provider-independent email value objects and normalization rules."""

from rosalind.domain.email.canonical import (
    CanonicalAttachment,
    CanonicalEmail,
    CanonicalObservation,
    CanonicalParticipant,
    CanonicalThread,
    message_uuid,
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
    "CanonicalAttachment",
    "CanonicalEmail",
    "CanonicalObservation",
    "CanonicalParticipant",
    "CanonicalThread",
    "EmailAddress",
    "EmailAttachment",
    "ParseWarning",
    "ParsedEmail",
    "ThreadEdge",
    "compute_thread_roots",
    "message_uuid",
    "normalize_message_id",
    "parse_message_ids",
]
