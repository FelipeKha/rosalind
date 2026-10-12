"""Fixture validation: pin the synthetic MBOX contract.

These tests parse the fixture directly (no Docker/Postgres) and assert the
corpus invariants the RAG gold set depends on, so an accidental fixture edit
fails here with a clear message instead of producing confusing downstream
retrieval failures.
"""

from __future__ import annotations

import mailbox
from collections.abc import Iterable
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "google"
    / "takeout"
    / "Mail"
    / "rosalind_synthetic_emails.mbox"
)

EXPECTED_MESSAGE_IDS = {
    f"<msg-{n:03d}@example.test>"
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18)
}


def _messages() -> list[mailbox.mboxMessage]:
    mbox = mailbox.mbox(str(FIXTURE))
    try:
        return list(mbox)
    finally:
        mbox.close()


def _by_id(messages: Iterable[mailbox.mboxMessage]) -> dict[str, mailbox.mboxMessage]:
    return {m["Message-ID"]: m for m in messages if m["Message-ID"]}


def test_corpus_has_18_messages_with_expected_ids() -> None:
    messages = _messages()

    assert len(messages) == 18
    assert {m["Message-ID"] for m in messages if m["Message-ID"]} == (
        EXPECTED_MESSAGE_IDS
    )


def test_one_message_has_no_message_id() -> None:
    messages = _messages()

    missing = [m for m in messages if not m["Message-ID"]]
    assert len(missing) == 1
    # The "Maintenance notice" from ops@example.test.
    assert missing[0]["Subject"] == "Maintenance notice"


def test_msg_016_has_invalid_date_value() -> None:
    by_id = _by_id(_messages())

    assert by_id["<msg-016@example.test>"]["Date"] == "not-a-valid-date"


def test_msg_008_has_pdf_attachment() -> None:
    by_id = _by_id(_messages())

    message = by_id["<msg-008@example.test>"]
    assert message.is_multipart()
    pdf = [
        part
        for part in message.walk()
        if part.get_content_type() == "application/pdf"
    ]
    assert len(pdf) == 1
    assert pdf[0].get_filename() == "q1-budget.pdf"


def test_spam_and_trash_labels() -> None:
    by_id = _by_id(_messages())

    assert by_id["<msg-013@example.test>"]["X-Gmail-Labels"] == "SPAM"
    assert by_id["<msg-014@example.test>"]["X-Gmail-Labels"] == "TRASH"


def test_msg_017_references_missing_parents() -> None:
    by_id = _by_id(_messages())

    message = by_id["<msg-017@example.test>"]
    assert message["In-Reply-To"] == "<msg-missing-parent@example.test>"
    references = message["References"] or ""
    assert "msg-root-migration@example.test" in references
    assert "msg-missing-parent@example.test" in references
    # Its references are not the migration-plan message.
    assert "msg-005@example.test" not in references
