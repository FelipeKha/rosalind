from datetime import UTC, datetime
from email.message import EmailMessage

from rosalind.adapters.inbound.ingestion.email import PARSER_VERSION, parse_email

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"


def _build(headers: dict[str, str]) -> EmailMessage:
    message = EmailMessage()
    for name, value in headers.items():
        message[name] = value
    return message


def _raw(message: EmailMessage) -> bytes:
    return message.as_bytes()


def test_parses_plain_text() -> None:
    message = _build(
        {
            "Message-ID": "<a@example.com>",
            "From": "Alice <alice@example.com>",
            "To": "Bob <bob@example.com>",
            "Subject": "hello",
        }
    )
    message.set_content("Body of the message.\n")

    parsed = parse_email(_raw(message))

    assert parsed.message_id == "a@example.com"
    assert parsed.subject == "hello"
    assert parsed.text_plain == "Body of the message.\n"
    assert parsed.text_html is None
    assert parsed.attachments == ()
    assert parsed.parse_warnings == ()


def test_parses_multipart_alternative() -> None:
    message = _build({"Message-ID": "<a@example.com>", "Subject": "hello"})
    message.set_content("plain body\n")
    message.add_alternative("<p>html body</p>\n", subtype="html")

    parsed = parse_email(_raw(message))

    assert parsed.text_plain == "plain body\n"
    assert parsed.text_html == "<p>html body</p>\n"
    assert parsed.attachments == ()


def test_parses_attachment() -> None:
    message = _build({"Message-ID": "<a@example.com>", "Subject": "quote"})
    message.set_content("see attached\n")
    message.add_attachment(
        PDF_BYTES, maintype="application", subtype="pdf", filename="quote.pdf"
    )

    parsed = parse_email(_raw(message))

    (attachment,) = parsed.attachments
    assert attachment.filename == "quote.pdf"
    assert attachment.declared_mime == "application/pdf"
    assert attachment.detected_mime == "application/pdf"
    assert attachment.size == len(PDF_BYTES)
    assert attachment.sha256
    assert attachment.disposition == "attachment"
    assert attachment.nested is None


def test_parses_inline_attachment() -> None:
    message = _build({"Message-ID": "<a@example.com>", "Subject": "logo"})
    message.set_content("body\n")
    message.make_mixed()
    part = EmailMessage()
    part.set_content(
        b"GIF89a",
        maintype="image",
        subtype="gif",
        disposition="inline",
        filename="logo.gif",
    )
    message.attach(part)

    parsed = parse_email(_raw(message))

    (attachment,) = parsed.attachments
    assert attachment.disposition == "inline"
    assert attachment.detected_mime == "image/gif"


def test_extracts_gmail_headers() -> None:
    message = _build(
        {
            "Message-ID": "<a@example.com>",
            "Subject": "projects",
            "X-GM-THRID": "1790123456789012345",
            "X-Gmail-Labels": "Inbox,Important,Projects",
        }
    )
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert parsed.provider_thread_hint == "1790123456789012345"
    assert parsed.provider_tags == ("Inbox", "Important", "Projects")


def test_extracts_references_and_in_reply_to() -> None:
    message = _build(
        {
            "Message-ID": "<reply@example.com>",
            "In-Reply-To": "<orig-001@mail.gmail.com>",
            "References": "<orig-001@mail.gmail.com> <orig-000@mail.gmail.com>",
            "Subject": "Re: roof",
        }
    )
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert parsed.in_reply_to == "orig-001@mail.gmail.com"
    assert parsed.references == ("orig-001@mail.gmail.com", "orig-000@mail.gmail.com")


def test_extracts_addresses_with_and_without_names() -> None:
    message = _build(
        {
            "Message-ID": "<a@example.com>",
            "From": "Mike Turner <mike@turnerroofing.com>",
            "To": "Alex Dupont <alex.dupont@gmail.com>",
            "Cc": "billing@turnerroofing.com",
            "Subject": "quote",
        }
    )
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert [(a.role, a.name, a.addr) for a in parsed.addresses] == [
        ("from", "Mike Turner", "mike@turnerroofing.com"),
        ("to", "Alex Dupont", "alex.dupont@gmail.com"),
        ("cc", None, "billing@turnerroofing.com"),
    ]


def test_parses_date_header_utc_and_offset() -> None:
    message = _build(
        {
            "Message-ID": "<a@example.com>",
            "Subject": "dated",
            "Date": "Tue, 17 Mar 2026 09:32:08 -0400",
        }
    )
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert parsed.date_header == "Tue, 17 Mar 2026 09:32:08 -0400"
    assert parsed.date_utc == datetime(2026, 3, 17, 13, 32, 8, tzinfo=UTC)
    assert parsed.date_offset_minutes == -240


def test_unparseable_date_warns() -> None:
    message = _build(
        {"Message-ID": "<a@example.com>", "Subject": "bad date", "Date": "not a date"}
    )
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert parsed.date_utc is None
    assert parsed.date_offset_minutes is None
    assert any(w.code == "unparseable_date" for w in parsed.parse_warnings)


def test_missing_message_id_warns() -> None:
    message = _build({"Subject": "no id"})
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert parsed.message_id is None
    assert any(w.code == "missing_message_id" for w in parsed.parse_warnings)


def test_forwarded_message_rfc822_is_nested() -> None:
    inner = _build(
        {
            "Message-ID": "<inner@example.com>",
            "From": "X <x@example.com>",
            "Subject": "fw",
        }
    )
    inner.set_content("inner body\n")

    outer = _build({"Message-ID": "<outer@example.com>", "Subject": "fwd"})
    outer.set_content("see forwarded\n")
    outer.add_attachment(inner)

    parsed = parse_email(_raw(outer))

    (attachment,) = parsed.attachments
    assert attachment.declared_mime == "message/rfc822"
    assert attachment.detected_mime is None
    assert attachment.nested is not None
    assert attachment.nested.message_id == "inner@example.com"
    assert attachment.nested.text_plain == "inner body\n"


def test_mime_mismatch_warns() -> None:
    message = _build({"Message-ID": "<a@example.com>", "Subject": "fake pdf"})
    message.set_content("body\n")
    message.add_attachment(
        b"this is actually plain text",
        maintype="application",
        subtype="pdf",
        filename="x.pdf",
    )

    parsed = parse_email(_raw(message))

    (attachment,) = parsed.attachments
    assert attachment.declared_mime == "application/pdf"
    assert attachment.detected_mime == "text/plain"
    assert any(w.code == "mime_mismatch" for w in parsed.parse_warnings)


def test_parser_version_is_stamped() -> None:
    message = _build({"Message-ID": "<a@example.com>"})
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert parsed.parser_version == PARSER_VERSION


def test_empty_message_parses_without_error() -> None:
    parsed = parse_email(b"")

    assert parsed.message_id is None
    assert parsed.subject is None
    assert parsed.attachments == ()
    assert any(w.code == "missing_message_id" for w in parsed.parse_warnings)


def test_parses_quoted_comma_labels() -> None:
    message = _build(
        {
            "Message-ID": "<a@example.com>",
            "Subject": "labels",
            "X-Gmail-Labels": 'Inbox,"Project, Alpha",Important',
        }
    )
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert parsed.provider_tags == ("Inbox", "Project, Alpha", "Important")


def test_extracts_delivered_to() -> None:
    message = _build(
        {
            "Message-ID": "<a@example.com>",
            "Subject": "delivered",
            "Delivered-To": "Alex <alex@example.com>",
        }
    )
    message.set_content("body\n")

    parsed = parse_email(_raw(message))

    assert parsed.delivered_to == "alex@example.com"


def test_attachment_carries_bytes_and_part_index() -> None:
    message = _build({"Message-ID": "<a@example.com>", "Subject": "two parts"})
    message.set_content("see attached\n")
    message.add_attachment(
        PDF_BYTES, maintype="application", subtype="pdf", filename="one.pdf"
    )
    message.add_attachment(
        PDF_BYTES, maintype="application", subtype="pdf", filename="two.pdf"
    )

    parsed = parse_email(_raw(message))

    assert [a.part_index for a in parsed.attachments] == [0, 1]
    assert all(a.data == PDF_BYTES for a in parsed.attachments)
    assert "PDF" not in repr(parsed.attachments[0])
