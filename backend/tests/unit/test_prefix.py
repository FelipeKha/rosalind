from dataclasses import replace
from datetime import UTC, datetime

from rosalind.domain.search import ChunkKind, PrefixContext, build_prefix

_DATE = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _ctx(**overrides) -> PrefixContext:
    ctx = PrefixContext(
        subject="Roof quote - 12 Elm Street",
        sender="Mike Turner <mike@turnerroofing.com>",
        recipients=("Alex Dupont <alex.dupont@gmail.com>", "billing@turnerroofing.com"),
        date=_DATE,
        attachment_filenames=("quote-2026-0412.pdf",),
    )
    return replace(ctx, **overrides)


def test_body_prefix() -> None:
    prefix = build_prefix(ChunkKind.EMAIL_BODY, _ctx())
    assert prefix.startswith("Email |")
    assert "subject: Roof quote - 12 Elm Street" in prefix
    assert "from: Mike Turner <mike@turnerroofing.com>" in prefix
    assert "date: 2026-03-17" in prefix
    assert "attachments: quote-2026-0412.pdf" in prefix


def test_prefix_is_deterministic() -> None:
    first = build_prefix(ChunkKind.EMAIL_BODY, _ctx())
    second = build_prefix(ChunkKind.EMAIL_BODY, _ctx())
    assert first == second


def test_long_subject_is_clipped() -> None:
    long_subject = "x" * 300
    prefix = build_prefix(ChunkKind.EMAIL_BODY, _ctx(subject=long_subject))
    assert len(long_subject) > 150
    assert "…" in prefix


def test_many_recipients_are_summarized() -> None:
    recipients = tuple(f"user{i}@example.com" for i in range(10))
    prefix = build_prefix(ChunkKind.EMAIL_BODY, _ctx(recipients=recipients))
    assert "+7" in prefix
    assert "user0@example.com" in prefix


def test_missing_from_omits_sender() -> None:
    prefix = build_prefix(ChunkKind.EMAIL_BODY, _ctx(sender=""))
    assert "from:" not in prefix


def test_no_attachments_omits_attachments() -> None:
    prefix = build_prefix(ChunkKind.EMAIL_BODY, _ctx(attachment_filenames=()))
    assert "attachments:" not in prefix


def test_quote_prefix() -> None:
    prefix = build_prefix(
        ChunkKind.EMAIL_QUOTE,
        _ctx(quoted_author="alex.dupont@gmail.com"),
    )
    assert prefix.startswith("Quoted history |")
    assert "in email: Roof quote - 12 Elm Street" in prefix
    assert "originally from: alex.dupont@gmail.com" in prefix


def test_attachment_prefix() -> None:
    prefix = build_prefix(
        ChunkKind.ATTACHMENT,
        PrefixContext(
            subject="Roof quote - 12 Elm Street",
            sender="Mike Turner <mike@turnerroofing.com>",
            recipients=(),
            date=_DATE,
            attachment_filename="quote-2026-0412.pdf",
        ),
    )
    assert prefix.startswith("Attachment |")
    assert "file: quote-2026-0412.pdf" in prefix
    assert "email subject: Roof quote - 12 Elm Street" in prefix
