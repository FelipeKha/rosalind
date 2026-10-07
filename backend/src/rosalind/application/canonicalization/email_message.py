"""Canonicalize a parsed email into the ``core.email_*`` model.

Owns the canonicalization *decisions*: direction, tag namespacing, thread root
selection, trash/spam detection, and the deterministic message id. All
persistence is delegated to the ``EmailCanonicalRepository`` port; attachment
blob bytes are written by the pipeline (which owns object storage), and this
module only computes their content-addressed keys.

Idempotency and re-observation are handled in the repository, not here: this
module always produces the current canonical form of one parsed message.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from rosalind.application.canonicalization.email import normalize_email
from rosalind.application.ports.repositories import EmailSaveResult
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.email import (
    CanonicalAttachment,
    CanonicalEmail,
    CanonicalObservation,
    CanonicalParticipant,
    CanonicalThread,
    ParsedEmail,
    content_sha256,
    message_uuid,
)
from rosalind.domain.source import SourceAccount, SourceRecord

CANONICALIZER_VERSION = "email/1.0.0"

BLOBS_NAMESPACE = "blobs"

_ROLES = ("from", "to", "cc", "bcc")

_SELF_LABEL = "self"
_SENT_LABEL = "sent"
_RECEIVED_LABEL = "received"
_UNKNOWN_LABEL = "unknown"

_TRASH_SPAM = {"spam", "trash"}


def blob_key(sha256: str) -> str:
    """Content-addressed object-storage key for an attachment blob."""
    return f"{BLOBS_NAMESPACE}/{sha256[:2]}/{sha256}"


def build_canonical_email(
    *,
    parsed: ParsedEmail,
    source_account: SourceAccount,
    source_record: SourceRecord,
    self_handles: set[str],
    observed_at: datetime,
    resource_type: str,
) -> CanonicalEmail:
    message_id, synthetic = _message_id(parsed, source_record)
    return CanonicalEmail(
        id=message_uuid(source_account.id, message_id),
        source_account_id=source_account.id,
        message_id=message_id,
        message_id_synthetic=synthetic,
        in_reply_to=parsed.in_reply_to,
        references=parsed.references,
        occurred_at=parsed.date_utc or observed_at,
        utc_offset_minutes=parsed.date_offset_minutes,
        direction=_direction(parsed, self_handles),
        subject=parsed.subject,
        text_plain=parsed.text_plain,
        text_html=parsed.text_html,
        content_sha256=content_sha256(parsed.text_plain, parsed.text_html),
        has_attachments=_has_attachments(parsed),
        is_trash_or_spam=_is_trash_or_spam(parsed),
        thread=CanonicalThread(
            root_message_id=_thread_root(parsed, message_id),
            provider_hint=parsed.provider_thread_hint,
        ),
        parser_version=parsed.parser_version,
        canonicalizer_version=CANONICALIZER_VERSION,
        parse_warnings=parsed.parse_warnings,
        observation=CanonicalObservation(
            source_record_id=source_record.id, observed_at=observed_at
        ),
        participants=_participants(parsed),
        attachments=_attachments(parsed),
        tags=_tags(parsed, resource_type),
    )


def _message_id(parsed: ParsedEmail, source_record: SourceRecord) -> tuple[str, bool]:
    if parsed.message_id is not None:
        return parsed.message_id, False
    return source_record.external_id, True


def _direction(parsed: ParsedEmail, self_handles: set[str]) -> str:
    labels = {label.strip().lower() for label in parsed.provider_tags}

    if _SENT_LABEL in labels:
        return _SENT_LABEL
    if _RECEIVED_LABEL in labels:
        return _RECEIVED_LABEL

    from_addr = _from_address(parsed)
    recipient_addrs = {
        normalize_email(address.addr)
        for address in parsed.addresses
        if address.role in ("to", "cc", "bcc")
    }

    from_is_self = from_addr is not None and from_addr in self_handles
    if from_is_self and recipient_addrs & self_handles:
        return _SELF_LABEL
    if from_is_self:
        return _SENT_LABEL
    if recipient_addrs & self_handles:
        return _RECEIVED_LABEL
    if (
        parsed.delivered_to is not None
        and normalize_email(parsed.delivered_to) in self_handles
    ):
        return _RECEIVED_LABEL
    return _UNKNOWN_LABEL


def _from_address(parsed: ParsedEmail) -> str | None:
    for address in parsed.addresses:
        if address.role == "from":
            return normalize_email(address.addr)
    return None


def _is_trash_or_spam(parsed: ParsedEmail) -> bool:
    return any(label.strip().lower() in _TRASH_SPAM for label in parsed.provider_tags)


def _has_attachments(parsed: ParsedEmail) -> bool:
    return any(
        attachment.disposition == "attachment" for attachment in parsed.attachments
    )


def _thread_root(parsed: ParsedEmail, message_id: str) -> str:
    if parsed.references:
        return parsed.references[0]
    if parsed.in_reply_to is not None:
        return parsed.in_reply_to
    return message_id


def _participants(parsed: ParsedEmail) -> tuple[CanonicalParticipant, ...]:
    participants: list[CanonicalParticipant] = []
    for role in _ROLES:
        role_addrs = [address for address in parsed.addresses if address.role == role]
        for seq, address in enumerate(role_addrs):
            participants.append(
                CanonicalParticipant(
                    role=role,
                    name=address.name,
                    addr=address.addr,
                    addr_normalized=normalize_email(address.addr),
                    seq=seq,
                )
            )
    return tuple(participants)


def _attachments(parsed: ParsedEmail) -> tuple[CanonicalAttachment, ...]:
    return tuple(
        CanonicalAttachment(
            filename=attachment.filename,
            declared_mime=attachment.declared_mime,
            detected_mime=attachment.detected_mime,
            size=attachment.size,
            sha256=attachment.sha256,
            disposition=attachment.disposition,
            storage_key=blob_key(attachment.sha256),
            part_index=attachment.part_index,
        )
        for attachment in parsed.attachments
    )


def _tags(parsed: ParsedEmail, resource_type: str) -> tuple[str, ...]:
    namespace = resource_type.split(".", 1)[0]
    return tuple(f"{namespace}:{label}" for label in parsed.provider_tags if label)


class EmailCanonicalizationService:
    """Thin orchestration between the pipeline and the email write port."""

    def self_handles(self, uow: UnitOfWork, account_id: uuid.UUID) -> set[str]:
        return uow.email_canonical.self_handles(account_id)

    def canonicalize(
        self, uow: UnitOfWork, canonical: CanonicalEmail
    ) -> EmailSaveResult:
        return uow.email_canonical.save(canonical)
