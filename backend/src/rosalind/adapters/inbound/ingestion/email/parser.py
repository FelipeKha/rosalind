"""Pure parser: raw RFC 822 message bytes → ``ParsedEmail``.

Stage 2.1 of the email pipeline. No database access, no object storage, no
network — it takes the bytes of one message and returns a provider-independent
observation for canonicalization. Gmail-specific headers (``X-GM-THRID``,
``X-Gmail-Labels``) are read here because Gmail Takeout mbox is the first
format; the resulting ``ParsedEmail`` keeps them as opaque provider data.
"""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

import magic as libmagic

from rosalind.domain.email import (
    EmailAddress,
    EmailAttachment,
    ParsedEmail,
    ParseWarning,
    normalize_message_id,
    parse_message_ids,
)

PARSER_VERSION = "gmail-mbox/1.3.0"

_MAX_NESTING_DEPTH = 8

_ADDRESS_ROLES = ("from", "to", "cc", "bcc")

_parser = BytesParser(policy=policy.default)


def parse_email(raw: bytes, _depth: int = 0) -> ParsedEmail:
    """Parse one RFC 822 message into a ``ParsedEmail`` observation."""
    message = _parser.parsebytes(raw)
    warnings: list[ParseWarning] = []

    message_id = _header_id(message["Message-ID"])
    if message_id is None:
        warnings.append(ParseWarning("missing_message_id", "message has no Message-ID"))

    subject = message["Subject"]
    date_utc, date_offset_minutes = _parse_date(message["Date"], warnings)

    addresses = _parse_addresses(message)
    text_plain, text_html, attachments = _walk(message, warnings, _depth)

    return ParsedEmail(
        message_id=message_id,
        in_reply_to=_last_reference(message["In-Reply-To"]),
        references=parse_message_ids(message["References"] or ""),
        provider_thread_hint=message["X-GM-THRID"],
        date_header=message["Date"],
        date_utc=date_utc,
        date_offset_minutes=date_offset_minutes,
        subject=subject,
        addresses=addresses,
        provider_tags=_parse_tags(message["X-Gmail-Labels"]),
        delivered_to=_first_delivered_to(message),
        text_plain=text_plain,
        text_html=text_html,
        attachments=attachments,
        parse_warnings=tuple(warnings),
        parser_version=PARSER_VERSION,
    )


def _header_id(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_message_id(value)


_MSG_ID_RE = re.compile(r"<([^<>]*)>")


def _last_reference(value: str | None) -> str | None:
    """Return the last valid Message-ID in an ``In-Reply-To`` header.

    The header may hold several IDs, or free text some clients insert. Only the
    last bracketed id (or, failing that, the last ``@``-bearing token) is kept;
    an unparseable value is treated as absent.
    """
    if value is None:
        return None
    bracketed = _MSG_ID_RE.findall(value)
    if bracketed:
        return normalize_message_id(bracketed[-1])
    for token in reversed(value.split()):
        token = token.strip()
        if "@" in token:
            return normalize_message_id(token)
    return None


def _parse_tags(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(tag.strip() for tag in _split_labels(value))


def _split_labels(value: str) -> list[str]:
    """Split a comma-separated label list, honoring quoted labels.

    Gmail label names may themselves contain commas; such labels are quoted in
    ``X-Gmail-Labels``. ``csv`` parses that correctly, so we reuse it.
    """
    return next(csv.reader([value]))


def _first_delivered_to(message) -> str | None:
    value = message["Delivered-To"]
    if value is None:
        return None
    for _name, addr in getaddresses([value]):
        if addr:
            return addr
    return None


def _parse_date(
    value: str | None, warnings: list[ParseWarning]
) -> tuple[datetime | None, int | None]:
    if value is None:
        return None, None
    try:
        parsed = parsedate_to_datetime(value)
    except TypeError, ValueError:
        warnings.append(
            ParseWarning("unparseable_date", f"could not parse Date: {value!r}")
        )
        return None, None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC), 0
    offset = parsed.utcoffset() or timedelta(0)
    offset_minutes = int(offset.total_seconds() // 60)
    return parsed.astimezone(UTC), offset_minutes


def _parse_addresses(message) -> tuple[EmailAddress, ...]:
    addresses: list[EmailAddress] = []
    for role in _ADDRESS_ROLES:
        raw_values = message.get_all(role, [])
        for name, addr in getaddresses(raw_values):
            if addr:
                addresses.append(EmailAddress(role=role, name=name or None, addr=addr))
    return tuple(addresses)


def _walk(
    message, warnings: list[ParseWarning], depth: int
) -> tuple[str | None, str | None, tuple[EmailAttachment, ...]]:
    """Collect body text and attachments in a single MIME tree traversal.

    ``message/rfc822`` parts are treated as attachments with a nested parse, never
    as body sources — the modern email API exposes their inner parts to
    ``iter_parts()``/``walk()``, and walking into them would leak the forwarded
    message's body into this one's ``text_plain``.
    """
    text_plain: str | None = None
    text_html: str | None = None
    attachments: list[EmailAttachment] = []
    part_index = 0

    def visit(part) -> None:
        nonlocal text_plain, text_html, part_index
        content_type = part.get_content_type()
        if content_type == "message/rfc822":
            attachments.append(_build_attachment(part, warnings, depth, part_index))
            part_index += 1
            return
        if part.get_content_maintype() == "multipart":
            for sub in part.iter_parts():
                visit(sub)
            return
        if content_type == "text/plain" and _is_body_part(part):
            if text_plain is None:
                text_plain = _decode_text(part, warnings)
            return
        if content_type == "text/html" and _is_body_part(part):
            if text_html is None:
                text_html = _decode_text(part, warnings)
            return
        if _is_attachment(part):
            attachments.append(_build_attachment(part, warnings, depth, part_index))
            part_index += 1

    visit(message)
    return text_plain, text_html, tuple(attachments)


def _is_body_part(part) -> bool:
    """A text part counts as body unless it is explicitly an attachment."""
    return (
        part.get_content_disposition() != "attachment" and part.get_filename() is None
    )


def _decode_text(part, warnings: list[ParseWarning]) -> str:
    try:
        content = part.get_content()
    except LookupError, UnicodeDecodeError, ValueError:
        warnings.append(
            ParseWarning(
                "undecodable_text", f"could not decode {part.get_content_type()}"
            )
        )
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", errors="replace") if payload else ""
    if isinstance(content, bytes):
        warnings.append(
            ParseWarning(
                "undecodable_text", f"could not decode {part.get_content_type()}"
            )
        )
        return content.decode("utf-8", errors="replace")
    return content


def _is_attachment(part) -> bool:
    if (
        part.get_content_disposition() == "attachment"
        or part.get_filename() is not None
    ):
        return True
    return part.get_content_type() not in ("text/plain", "text/html")


def _build_attachment(
    part, warnings: list[ParseWarning], depth: int, part_index: int
) -> EmailAttachment:
    content_type = part.get_content_type()
    filename = part.get_filename()
    disposition = part.get_content_disposition()
    if disposition is None:
        disposition = "attachment" if filename else "inline"

    payload = part.get_payload(decode=True)
    decoded = payload if payload is not None else b""

    nested: ParsedEmail | None = None
    detected_mime: str | None = None
    if content_type == "message/rfc822":
        # The embedded message is a parsed Message object; re-serialize it to
        # recover its bytes (``decode=True`` yields nothing for message/rfc822).
        embedded = part.get_content()
        if hasattr(embedded, "as_bytes"):
            decoded = embedded.as_bytes()
        else:
            decoded = part.get_payload(decode=True) or b""
        if depth >= _MAX_NESTING_DEPTH:
            warnings.append(
                ParseWarning("max_nesting", "nested message/rfc822 exceeds max depth")
            )
        else:
            nested = parse_email(decoded, _depth=depth + 1)
    else:
        detected_mime = _detect_mime(decoded, warnings)
        if (
            content_type != "application/octet-stream"
            and detected_mime is not None
            and not _mime_matches(content_type, detected_mime)
        ):
            warnings.append(
                ParseWarning(
                    "mime_mismatch",
                    f"declared {content_type!r} disagrees with detected "
                    f"{detected_mime!r}",
                )
            )

    return EmailAttachment(
        filename=filename,
        declared_mime=content_type,
        detected_mime=detected_mime,
        size=len(decoded),
        sha256=hashlib.sha256(decoded).hexdigest(),
        disposition=disposition,
        part_index=part_index,
        nested=nested,
        data=decoded,
    )


def _detect_mime(decoded: bytes, warnings: list[ParseWarning]) -> str | None:
    try:
        return libmagic.from_buffer(decoded, mime=True)
    except Exception:  # noqa: BLE001 - sniffing is best-effort, never fatal
        warnings.append(
            ParseWarning("mime_detect_failed", "magic-byte sniffing failed")
        )
        return None


def _mime_matches(declared: str, detected: str) -> bool:
    declared_main = declared.split("/", 1)[0].lower()
    detected_main = detected.split("/", 1)[0].lower()
    return declared_main == detected_main
