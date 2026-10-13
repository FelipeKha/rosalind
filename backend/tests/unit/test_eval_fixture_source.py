"""Tests for the fixture mailbox passage source."""

from __future__ import annotations

import uuid

from rosalind.domain.email import message_uuid
from tests.eval_support import (
    FIXTURE_SOURCE_ACCOUNT_ID,
    item_id_for,
    iter_fixture_passages,
    mailbox_path,
)


def test_fixture_mailbox_exists() -> None:
    assert mailbox_path().exists()


def test_item_id_is_deterministic() -> None:
    expected = str(message_uuid(FIXTURE_SOURCE_ACCOUNT_ID, "msg-001@example.test"))
    assert item_id_for("msg-001@example.test") == expected


def test_fixture_has_enough_emails() -> None:
    assert len(iter_fixture_passages()) >= 50


def test_trash_is_excluded_by_default() -> None:
    default = {p.message_id for p in iter_fixture_passages()}
    included = {p.message_id for p in iter_fixture_passages(include_trash_spam=True)}
    assert "msg-018@example.test" not in default
    assert "msg-018@example.test" in included


def test_roof_quote_attachment_is_present() -> None:
    passages = {p.message_id: p for p in iter_fixture_passages()}
    attachment = passages["msg-001@example.test"].attachment_sha256
    assert attachment is not None
    assert len(attachment) == 64
    assert all(c in "0123456789abcdef" for c in attachment)


def test_html_only_message_has_text() -> None:
    passages = {p.message_id: p for p in iter_fixture_passages()}
    assert "25 March" in passages["msg-015@example.test"].text


def test_item_ids_are_uuids() -> None:
    for passage in iter_fixture_passages():
        uuid.UUID(passage.item_id)
