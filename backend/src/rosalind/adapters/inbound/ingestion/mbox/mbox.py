"""Streaming splitter for mbox archives.

Pure function: takes an mbox archive and yields one ``SplitMessage`` per
message. No database access, no object storage, no network. The caller is
responsible for defining the fallback ``external_id`` when a message has no
``Message-ID`` header (see ``EmailProcessingService``).
"""

from __future__ import annotations

import mailbox
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from rosalind.domain.email import normalize_message_id


@dataclass(frozen=True)
class SplitMessage:
    """One message cut from an mbox archive.

    ``raw`` is the serialized RFC 822 message. ``message_id`` is the
    normalized ``Message-ID`` header (angle brackets stripped), or ``None``
    when the header is absent.
    """

    raw: bytes
    message_id: str | None


def iter_messages(source: str | Path) -> Iterator[SplitMessage]:
    """Yield one ``SplitMessage`` per message in the mbox at ``source``.

    ``mailbox.mbox`` builds an in-memory table of contents of byte offsets and
    loads each body lazily, so iteration is memory-bounded even for very large
    archives.
    """
    mbox = mailbox.mbox(str(source))
    try:
        for message in mbox:
            yield SplitMessage(
                raw=message.as_bytes(),
                message_id=_message_id(message),
            )
    finally:
        mbox.close()


def _message_id(message: mailbox.mboxMessage) -> str | None:
    header = message.get("Message-ID")
    if not header:
        return None
    return normalize_message_id(header.strip())
