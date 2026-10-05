"""Message-ID normalization shared across email pipeline stages.

``Message-ID`` (and the ``In-Reply-To``/``References`` headers that reference
them) are a single identifier concept: the record split (``raw.source_record``)
and the parse stage (``ParsedEmail``) must agree on the same representation or
they cannot be joined during canonicalization. Normalization is a domain rule,
so it lives here, not in either adapter.
"""

from __future__ import annotations


def normalize_message_id(value: str) -> str:
    """Return a canonical ``Message-ID`` with surrounding angle brackets removed.

    ``<CAF7x9=roof-2291@mail.gmail.com>`` → ``CAF7x9=roof-2291@mail.gmail.com``.
    Idempotent: ``normalize(normalize(x)) == normalize(x)``.
    """
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        return value[1:-1].strip()
    return value


def parse_message_ids(value: str) -> tuple[str, ...]:
    """Split a ``References``/``In-Reply-To`` header into normalized message IDs."""
    return tuple(normalize_message_id(part) for part in value.split() if part.strip())
