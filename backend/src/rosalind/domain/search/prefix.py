"""Contextual prefix builder for chunks (pure, versioned).

A chunk must read standalone when surfaced out of its email. The prefix adds
the subject, sender, recipients, date, and attachments in a language-neutral
way: ISO dates, no localized month names, bounded lengths. ``PREFIX_VERSION``
(defined in ``chunks``) gates changes to this template through the index
version.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rosalind.domain.search.chunks import ChunkKind

_SUBJECT_LIMIT = 150
_RECIPIENT_LIMIT = 3
_ATTACHMENT_LIMIT = 5


@dataclass(frozen=True)
class PrefixContext:
    """Resolved fields the prefix needs for one source (message or attachment)."""

    subject: str | None
    sender: str  # "Name <addr>" or bare address
    recipients: tuple[str, ...]  # display strings, in header order
    date: datetime | None
    attachment_filenames: tuple[str, ...] = ()
    quoted_author: str | None = None
    attachment_filename: str | None = None


def build_prefix(kind: ChunkKind, ctx: PrefixContext) -> str:
    """Build the prefix for one chunk of ``kind`` from its context."""
    if kind is ChunkKind.EMAIL_QUOTE:
        return _quote_prefix(ctx)
    if kind is ChunkKind.ATTACHMENT:
        return _attachment_prefix(ctx)
    return _body_prefix(ctx)


def _body_prefix(ctx: PrefixContext) -> str:
    parts = ["Email"]
    if ctx.subject:
        parts.append(f"subject: {_clip(ctx.subject, _SUBJECT_LIMIT)}")
    if ctx.sender:
        parts.append(f"from: {ctx.sender}")
    if ctx.recipients:
        parts.append(f"to: {_list(ctx.recipients, _RECIPIENT_LIMIT)}")
    if ctx.date is not None:
        parts.append(f"date: {_date(ctx.date)}")
    if ctx.attachment_filenames:
        parts.append(
            f"attachments: {_list(ctx.attachment_filenames, _ATTACHMENT_LIMIT)}"
        )
    return " | ".join(parts)


def _quote_prefix(ctx: PrefixContext) -> str:
    parts = ["Quoted history"]
    if ctx.subject:
        parts.append(f"in email: {_clip(ctx.subject, _SUBJECT_LIMIT)}")
    if ctx.sender:
        parts.append(f"from: {ctx.sender}")
    if ctx.date is not None:
        parts.append(f"date: {_date(ctx.date)}")
    if ctx.quoted_author:
        parts.append(f"originally from: {ctx.quoted_author}")
    return " | ".join(parts)


def _attachment_prefix(ctx: PrefixContext) -> str:
    parts = ["Attachment"]
    if ctx.attachment_filename:
        parts.append(f"file: {ctx.attachment_filename}")
    if ctx.subject:
        parts.append(f"email subject: {_clip(ctx.subject, _SUBJECT_LIMIT)}")
    if ctx.sender:
        parts.append(f"from: {ctx.sender}")
    if ctx.date is not None:
        parts.append(f"date: {_date(ctx.date)}")
    return " | ".join(parts)


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _list(items: tuple[str, ...], limit: int) -> str:
    shown = items[:limit]
    remainder = len(items) - len(shown)
    if remainder > 0:
        return ", ".join(shown) + f", +{remainder}"
    return ", ".join(shown)


def _date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")
