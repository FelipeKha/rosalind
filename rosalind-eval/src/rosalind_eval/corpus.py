"""Synthetic fixture corpus and passage iteration for rosalind-eval.

The fixture mailbox is a small, deterministic mbox with no private data, so CI
can run the whole pipeline without a real mailbox. Item ids are derived with the
same ``message_uuid`` function the app uses, against a fixed fixture source
account id, so gold labels are stable and git-versionable.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from rosalind.adapters.inbound.ingestion.email import parse_email
from rosalind.adapters.inbound.ingestion.mbox import iter_messages
from rosalind.domain.email import message_uuid

__all__ = [
    "FIXTURE_SOURCE_ACCOUNT_ID",
    "Passage",
    "dataset_path",
    "fixture_dir",
    "item_id_for",
    "iter_passages",
    "known_item_ids_from_mailbox",
    "mailbox_path",
]

# Fixed so canonical item ids are reproducible across imports: the real app
# derives email_message.id = uuid5(NAMESPACE, f"{source_account_id}:{message_id}").
FIXTURE_SOURCE_ACCOUNT_ID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")

_TRASH_SPAM = {"trash", "spam"}


def item_id_for(message_id: str) -> str:
    """The canonical item id the fixture import yields for ``message_id``."""
    return str(message_uuid(FIXTURE_SOURCE_ACCOUNT_ID, message_id))


def fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures"


def mailbox_path() -> Path:
    return fixture_dir() / "mailbox.mbox"


def dataset_path() -> Path:
    return fixture_dir() / "dataset.jsonl"


@dataclass(frozen=True)
class Passage:
    """One fixture message reduced to what question generation needs."""

    item_id: str
    message_id: str
    subject: str | None
    text: str
    attachment_sha256: str | None


def iter_passages(
    mailbox: str | Path | None = None,
    *,
    include_trash_spam: bool = False,
) -> Iterator[Passage]:
    """Yield one passage per fixture message, skipping trashed/spam mail by default."""
    source = Path(mailbox) if mailbox is not None else mailbox_path()
    for split in iter_messages(source):
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
            (a for a in parsed.attachments if a.disposition == "attachment"), None
        )
        yield Passage(
            item_id=item_id_for(split.message_id),
            message_id=split.message_id,
            subject=parsed.subject,
            text=text,
            attachment_sha256=attachment.sha256 if attachment else None,
        )


def known_item_ids_from_mailbox(mailbox: str | Path | None = None) -> frozenset[str]:
    """Every item id the fixture import would create, for existence checks."""
    source = Path(mailbox) if mailbox is not None else mailbox_path()
    ids: set[str] = set()
    for split in iter_messages(source):
        if split.message_id is None:
            continue
        ids.add(item_id_for(split.message_id))
    return frozenset(ids)
