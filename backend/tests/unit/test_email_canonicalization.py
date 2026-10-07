from datetime import UTC, datetime
from uuid import uuid4

from rosalind.application.canonicalization.email_message import (
    CANONICALIZER_VERSION,
    blob_key,
    build_canonical_email,
    message_uuid,
)
from rosalind.domain.email import EmailAddress, EmailAttachment, ParsedEmail
from rosalind.domain.source import SourceAccount, SourceRecord

SELF = {"me@example.com"}


def _account() -> SourceAccount:
    return SourceAccount(
        id=uuid4(),
        account_id=uuid4(),
        provider="google",
        name="google-personal",
        account_identifier=None,
        display_name=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _record(external_id: str = "m@example.com") -> SourceRecord:
    return SourceRecord(
        id=uuid4(),
        source_account_id=uuid4(),
        resource_type="gmail.message",
        external_id=external_id,
        payload=None,
        payload_sha256="a" * 64,
    )


def _parsed(
    *,
    message_id: str | None = "m@example.com",
    addresses: tuple[EmailAddress, ...] = (),
    tags: tuple[str, ...] = (),
    delivered_to: str | None = None,
    references: tuple[str, ...] = (),
    in_reply_to: str | None = None,
    date_utc: datetime | None = None,
    attachments: tuple[EmailAttachment, ...] = (),
) -> ParsedEmail:
    return ParsedEmail(
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        provider_thread_hint=None,
        date_header=None,
        date_utc=date_utc,
        date_offset_minutes=None,
        subject=None,
        addresses=addresses,
        provider_tags=tags,
        delivered_to=delivered_to,
        text_plain=None,
        text_html=None,
        attachments=attachments,
        parse_warnings=(),
        parser_version="gmail-mbox/1.0.0",
    )


def _addr(role: str, addr: str) -> EmailAddress:
    return EmailAddress(role=role, name=None, addr=addr)


def _attachment(disposition: str, part_index: int = 0) -> EmailAttachment:
    return EmailAttachment(
        filename="x.pdf",
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        size=10,
        sha256="b" * 64,
        disposition=disposition,
        part_index=part_index,
        data=b"data",
    )


def _build(parsed: ParsedEmail) -> dict:
    canonical = build_canonical_email(
        parsed=parsed,
        source_account=_account(),
        source_record=_record(parsed.message_id or "no-message-id:abc"),
        self_handles=SELF,
        observed_at=datetime(2026, 1, 2, tzinfo=UTC),
        resource_type="gmail.message",
    )
    return {
        "id": canonical.id,
        "message_id": canonical.message_id,
        "synthetic": canonical.message_id_synthetic,
        "direction": canonical.direction,
        "tags": canonical.tags,
        "trash": canonical.is_trash_or_spam,
        "has_attachments": canonical.has_attachments,
        "thread_root": canonical.thread.root_message_id,
        "occurred_at": canonical.occurred_at,
        "canonicalizer_version": canonical.canonicalizer_version,
    }


def test_direction_received_when_recipient_is_self() -> None:
    parsed = _parsed(
        addresses=(_addr("to", "me@example.com"), _addr("from", "x@y.com"))
    )
    assert _build(parsed)["direction"] == "received"


def test_direction_sent_when_from_is_self() -> None:
    parsed = _parsed(
        addresses=(_addr("from", "me@example.com"), _addr("to", "x@y.com"))
    )
    assert _build(parsed)["direction"] == "sent"


def test_direction_self_when_from_and_to_are_self() -> None:
    parsed = _parsed(
        addresses=(_addr("from", "me@example.com"), _addr("to", "me@example.com"))
    )
    assert _build(parsed)["direction"] == "self"


def test_direction_unknown_when_no_signal() -> None:
    parsed = _parsed(addresses=(_addr("from", "a@y.com"), _addr("to", "b@y.com")))
    assert _build(parsed)["direction"] == "unknown"


def test_direction_from_labels() -> None:
    parsed = _parsed(tags=("Sent",), addresses=())
    assert _build(parsed)["direction"] == "sent"


def test_direction_from_delivered_to() -> None:
    parsed = _parsed(delivered_to="me@example.com", addresses=())
    assert _build(parsed)["direction"] == "received"


def test_tags_are_namespaced() -> None:
    parsed = _parsed(tags=("Inbox", "Projects"))
    assert _build(parsed)["tags"] == ("gmail:Inbox", "gmail:Projects")


def test_trash_or_spam() -> None:
    assert _build(_parsed(tags=("Trash",)))["trash"] is True
    assert _build(_parsed(tags=("Inbox",)))["trash"] is False


def test_has_attachments_excludes_inline() -> None:
    assert (
        _build(_parsed(attachments=(_attachment("attachment"),)))["has_attachments"]
        is True
    )
    assert (
        _build(_parsed(attachments=(_attachment("inline"),)))["has_attachments"]
        is False
    )


def test_thread_root_priority() -> None:
    assert (
        _build(_parsed(references=("root@x.com", "mid@x.com")))["thread_root"]
        == "root@x.com"
    )
    assert _build(_parsed(in_reply_to="parent@x.com"))["thread_root"] == "parent@x.com"
    assert _build(_parsed(message_id="self@x.com"))["thread_root"] == "self@x.com"


def test_missing_message_id_is_synthetic() -> None:
    parsed = _parsed(message_id=None)
    result = _build(parsed)
    assert result["synthetic"] is True
    assert result["message_id"] == "no-message-id:abc"


def test_occurred_at_falls_back_to_observed_at() -> None:
    parsed = _parsed(message_id="m@x.com")
    assert _build(parsed)["occurred_at"] == datetime(2026, 1, 2, tzinfo=UTC)


def test_message_uuid_is_deterministic() -> None:
    account_id = uuid4()
    assert message_uuid(account_id, "m@x.com") == message_uuid(account_id, "m@x.com")
    assert message_uuid(account_id, "m@x.com") != message_uuid(
        account_id, "other@x.com"
    )
    assert message_uuid(account_id, "m@x.com") != message_uuid(uuid4(), "m@x.com")


def test_canonicalizer_version_is_stamped() -> None:
    assert _build(_parsed())["canonicalizer_version"] == CANONICALIZER_VERSION


def test_blob_key_is_content_addressed() -> None:
    sha = "e5a1" * 16
    assert blob_key(sha) == f"blobs/{sha[:2]}/{sha}"
