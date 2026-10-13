"""Mailbox passage source.

Implements the ``PassageSource`` port by reading an mbox with the same splitter
and parser the ingestion pipeline uses. Item ids are derived with the app's
``message_uuid`` when a source-account id is supplied; otherwise the RFC
``message_id`` is used as a placeholder for draft questions to be re-keyed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

from rosalind.adapters.inbound.ingestion.email import parse_email
from rosalind.adapters.inbound.ingestion.mbox import iter_messages
from rosalind.application.eval.models import Passage
from rosalind.domain.email import message_uuid

__all__ = ["MailboxPassageSource"]

_TRASH_SPAM = {"trash", "spam"}


class MailboxPassageSource:
    def __init__(self, source_account_id: uuid.UUID | None = None) -> None:
        self._source_account_id = source_account_id

    def iter_passages(
        self, mailbox: str | Path, *, include_trash_spam: bool = False
    ) -> Iterator[Passage]:
        for split in iter_messages(Path(mailbox)):
            if split.message_id is None:
                continue
            parsed = parse_email(split.raw)
            if not include_trash_spam and any(
                tag.strip().lower() in _TRASH_SPAM for tag in parsed.provider_tags
            ):
                continue
            text = parsed.text_plain or parsed.text_html or ""
            if not text.strip():
                continue
            attachment = next(
                (a for a in parsed.attachments if a.disposition == "attachment"),
                None,
            )
            item_id = (
                str(message_uuid(self._source_account_id, split.message_id))
                if self._source_account_id is not None
                else split.message_id
            )
            yield Passage(
                item_id=item_id,
                message_id=split.message_id,
                subject=parsed.subject,
                text=text,
                attachment_sha256=attachment.sha256 if attachment else None,
            )
