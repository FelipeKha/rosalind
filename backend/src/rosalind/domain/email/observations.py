"""Provider-independent parsed-email observations.

These value objects record *what the parse stage extracted* from a raw RFC 822
message, before any canonicalization into ``item.email``. They are transient:
they are regenerated from ``raw.source_record`` whenever needed and are never
persisted directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rosalind.domain.email.message_id import normalize_message_id, parse_message_ids

__all__ = [
    "EmailAddress",
    "EmailAttachment",
    "ParseWarning",
    "ParsedEmail",
    "normalize_message_id",
    "parse_message_ids",
]


@dataclass(frozen=True)
class EmailAddress:
    """One address header entry with its role (``from``, ``to``, ``cc``, ``bcc``)."""

    role: str
    name: str | None
    addr: str


@dataclass(frozen=True)
class EmailAttachment:
    """One MIME part treated as an attachment.

    ``declared_mime`` is what the ``Content-Type`` header says; ``detected_mime``
    is what magic-byte sniffing found. They may disagree — that is a parse
    warning, not a silent override. ``effective_mime`` is deliberately *not*
    stored: it is derived later (detected when reliable, else declared) by
    whoever consumes the attachment.
    """

    filename: str | None
    declared_mime: str | None
    detected_mime: str | None
    size: int
    sha256: str
    disposition: str
    nested: ParsedEmail | None = None


@dataclass(frozen=True)
class ParseWarning:
    """A non-fatal problem found while parsing a message."""

    code: str
    message: str


@dataclass(frozen=True)
class ParsedEmail:
    """Structured result of parsing a single RFC 822 message."""

    message_id: str | None
    in_reply_to: str | None
    references: tuple[str, ...]
    provider_thread_hint: str | None
    date_header: str | None
    date_utc: datetime | None
    date_offset_minutes: int | None
    subject: str | None
    addresses: tuple[EmailAddress, ...]
    provider_tags: tuple[str, ...]
    text_plain: str | None
    text_html: str | None
    attachments: tuple[EmailAttachment, ...]
    parse_warnings: tuple[ParseWarning, ...]
    parser_version: str
