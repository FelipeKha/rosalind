"""Clean-text preparation for the enrich stage (pure, versioned heuristics).

Every choice here is a versioned heuristic: changing it bumps ``TEXTPREP_VERSION``
and therefore invalidates the derived rows it produced. The functions are pure
and side-effect free — no HTML parsing, no language detection, no I/O.

Cleaning is deterministic and happens *before* segmentation, so offsets are
computed against the cleaned text that is actually stored.
"""

from __future__ import annotations

import re
import unicodedata

from rosalind.domain.email.html import HtmlDocument

TEXTPREP_VERSION = "textprep/1"

# A plain part shorter than this fraction of the HTML-derived text is treated as
# a "view in browser" stub. Versioned: changing it changes ``TEXTPREP_VERSION``.
_STUB_LENGTH_RATIO = 0.1

# A plain part whose non-whitespace characters are mostly URLs is treated as a
# stub ("view in browser") regardless of length.
_STUB_URL_RATIO = 0.8

_HSPACE = re.compile(r" +")
_URL = re.compile(r"https?://\S+")
_NON_SPACE = re.compile(r"\s+")


def clean_plain(text: str) -> str:
    """Normalize a plain-text body for storage.

    - Unicode NFC normalization.
    - Line endings folded to ``\\n``.
    - Control characters (NUL, DEL, C0/C1) stripped; ``\\n`` and ``\\t`` kept.
    - Whitespace collapsed *within* lines; newlines preserved. Leading/trailing
      horizontal whitespace is kept so the ``-- `` signature delimiter survives.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned: list[str] = []
    for ch in text:
        code = ord(ch)
        if code in (0x0A, 0x09):
            cleaned.append(ch)
        elif code < 0x20 or 0x7F <= code < 0xA0:
            continue
        else:
            cleaned.append(ch)
    return _collapse_within_lines("".join(cleaned))


def _collapse_within_lines(text: str) -> str:
    return "\n".join(_HSPACE.sub(" ", line) for line in text.split("\n"))


def is_mostly_urls(text: str) -> bool:
    """True when most of a text's non-whitespace characters are URLs."""
    stripped = _NON_SPACE.sub("", text)
    if not stripped:
        return False
    urls = "".join(_URL.findall(text))
    return len(urls) / len(stripped) > _STUB_URL_RATIO


def _usable_plain(text_plain: str | None, html_text: str) -> bool:
    if not text_plain or not text_plain.strip():
        return False
    if is_mostly_urls(text_plain):
        return False
    return not html_text or len(text_plain) >= _STUB_LENGTH_RATIO * len(html_text)


def select_clean_text(
    text_plain: str | None, html_doc: HtmlDocument | None
) -> tuple[str, str]:
    """Choose the clean-text source for one message.

    Structure-first: an HTML part with a recognized quote structure wins, because
    structural markers are language-independent. Otherwise a usable (non-stub)
    plain part wins; otherwise the HTML-derived text; otherwise empty.
    """
    if html_doc is not None and html_doc.has_quote_structure:
        return html_doc.text, "html"
    html_text = html_doc.text if html_doc is not None else ""
    if text_plain and _usable_plain(text_plain, html_text):
        return clean_plain(text_plain), "plain"
    if html_doc is not None:
        return html_doc.text, "html"
    if text_plain:
        return clean_plain(text_plain), "plain"
    return "", "plain"
