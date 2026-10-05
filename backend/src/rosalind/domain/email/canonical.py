"""Canonical email aggregate for the canonicalization stage.

``CanonicalEmail`` is the frozen value object the canonicalization service
builds from a ``ParsedEmail`` (plus provenance and blob storage keys) and hands
to the ``EmailCanonicalRepository`` port. It is the single atomic unit the
repository persists, so one message — with its observation, participants,
attachments, tags, and thread — is written together.

The message id is a deterministic ``uuid5`` over ``(source_account_id,
message_id)`` so rebuilding canonical tables from raw yields identical ids
(keeps eval ground truth, citations, and audit logs valid across a rebuild).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from rosalind.domain.email.observations import ParseWarning

# A fixed, Rosalind-specific namespace for email message UUIDs. Deliberately
# arbitrary but stable: it must never change or previously-built ids would.
EMAIL_MESSAGE_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def message_uuid(source_account_id: uuid.UUID, message_id: str) -> uuid.UUID:
    """Deterministic canonical id for an email message."""
    return uuid.uuid5(EMAIL_MESSAGE_NAMESPACE, f"{source_account_id}:{message_id}")


@dataclass(frozen=True)
class CanonicalObservation:
    """Provenance: the raw record this message was canonicalized from."""

    source_record_id: uuid.UUID
    observed_at: datetime


@dataclass(frozen=True)
class CanonicalThread:
    """Thread key for the simple store (full reconciliation is deferred)."""

    root_message_id: str
    provider_hint: str | None


@dataclass(frozen=True)
class CanonicalParticipant:
    role: str
    name: str | None
    addr: str
    addr_normalized: str
    seq: int


@dataclass(frozen=True)
class CanonicalAttachment:
    filename: str | None
    declared_mime: str | None
    detected_mime: str | None
    size: int
    sha256: str
    disposition: str
    storage_key: str
    part_index: int


@dataclass(frozen=True)
class CanonicalEmail:
    id: uuid.UUID
    source_account_id: uuid.UUID
    message_id: str
    message_id_synthetic: bool
    in_reply_to: str | None
    references: tuple[str, ...]
    occurred_at: datetime
    utc_offset_minutes: int | None
    direction: str
    subject: str | None
    text_plain: str | None
    text_html: str | None
    has_attachments: bool
    is_trash_or_spam: bool
    thread: CanonicalThread
    parser_version: str
    canonicalizer_version: str
    parse_warnings: tuple[ParseWarning, ...]
    observation: CanonicalObservation
    participants: tuple[CanonicalParticipant, ...]
    attachments: tuple[CanonicalAttachment, ...]
    tags: tuple[str, ...]
