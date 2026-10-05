"""Provider-neutral HTML structure handed to the segmentation rules.

The HTML parser adapter (``adapters.outbound.enrichment.html``) turns an
``text/html`` part into this neutral structure; the domain segmentation rules
consume it without any knowledge of selectolax or HTML parsing. The adapter
guarantees ``blocks`` tile ``text`` (no gaps or overlaps) so segmentation can
reason purely in code-point offsets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HtmlBlock:
    """One contiguous, same-kind span of an HTML message's text."""

    kind: str  # 'body' | 'quote' | 'signature'
    text: str
    start: int
    end: int
    quote_depth: int = 0
    attribution: str | None = None


@dataclass(frozen=True)
class HtmlDocument:
    """Cleaned text plus the structural blocks an HTML message decomposes into.

    ``text`` is already normalized (NFC, control characters stripped, whitespace
    collapsed within lines, newlines preserved) by the adapter.
    """

    text: str
    blocks: tuple[HtmlBlock, ...]
    has_quote_structure: bool
