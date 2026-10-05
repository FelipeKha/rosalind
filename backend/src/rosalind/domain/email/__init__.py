"""Provider-independent email value objects and normalization rules."""

from rosalind.domain.email.message_id import normalize_message_id, parse_message_ids
from rosalind.domain.email.observations import (
    EmailAddress,
    EmailAttachment,
    ParsedEmail,
    ParseWarning,
)

__all__ = [
    "EmailAddress",
    "EmailAttachment",
    "ParseWarning",
    "ParsedEmail",
    "normalize_message_id",
    "parse_message_ids",
]
