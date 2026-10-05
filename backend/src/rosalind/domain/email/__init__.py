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
    "message_uuid",
    "normalize_message_id",
    "parse_message_ids",
]
