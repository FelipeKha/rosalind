"""selectolax (lexbor) HTML parser adapter for the enrich stage.

Turns an ``text/html`` body into the neutral ``HtmlDocument`` structure the
domain segmentation rules consume. The walk is iterative (an explicit stack, no
Python recursion) so deeply nested HTML cannot overflow the stack, and it never
fetches remote resources.

Recognized structural markers (confirm against real mail before relying on
them):
- Gmail quote: a container whose class contains ``gmail_quote``; attribution in
  ``gmail_attr``; signature in ``gmail_signature``.
- Apple Mail quote: ``blockquote[type=cite]``.
"""

from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser, LexborNode

from rosalind.domain.email.html import HtmlBlock, HtmlDocument
from rosalind.domain.email.text import clean_plain

VERSION = "selectolax/1"

_SKIP_TAGS = frozenset(
    {"script", "style", "head", "title", "meta", "link", "noscript", "template"}
)

# Elements that introduce a line break in the extracted text.
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)


class SelectolaxHtmlParser:
    version = VERSION

    def parse(self, html: str) -> HtmlDocument:
        parser = LexborHTMLParser(html)
        root = parser.root
        if root is None:
            return HtmlDocument(text="", blocks=(), has_quote_structure=False)

        raw_blocks = _walk(root)

        blocks: list[HtmlBlock] = []
        has_quote = False
        position = 0
        for kind, depth, attribution, raw_text in raw_blocks:
            text = clean_plain(raw_text)
            if not text.strip():
                continue
            if kind == "quote":
                has_quote = True
            text += "\n"
            blocks.append(
                HtmlBlock(
                    kind=kind,
                    text=text,
                    start=position,
                    end=position + len(text),
                    quote_depth=depth,
                    attribution=attribution,
                )
            )
            position += len(text)

        return HtmlDocument(
            text="".join(block.text for block in blocks),
            blocks=tuple(blocks),
            has_quote_structure=has_quote,
        )


def _walk(root: LexborNode) -> list[tuple[str, int, str | None, str]]:
    """Iteratively collect ``(kind, depth, attribution, text)`` blocks."""
    blocks: list[tuple[str, int, str | None, str]] = []

    cur_kind = "body"
    cur_depth = 0
    cur_attr: str | None = None
    buffer: list[str] = []

    def flush() -> str:
        nonlocal buffer
        text = "".join(buffer)
        buffer = []
        return text

    stack: list[tuple[LexborNode, str, int, str | None]] = [(root, "body", 0, None)]
    while stack:
        node, kind, depth, attr = stack.pop()
        tag = node.tag
        if tag in _SKIP_TAGS or _is_hidden(node):
            continue

        nkind, ndepth, nattr = kind, depth, attr
        if _is_quote(node):
            nkind, ndepth = "quote", depth + 1
        elif _is_signature(node):
            nkind = "signature"
        if _is_attr(node):
            nattr = (node.text(deep=True) or "").strip() or attr

        if nkind != cur_kind or ndepth != cur_depth:
            blocks.append((cur_kind, cur_depth, cur_attr, flush()))
            cur_kind, cur_depth, cur_attr = nkind, ndepth, nattr
        elif cur_attr is None and nattr is not None:
            cur_attr = nattr

        own = node.text(deep=False) or ""
        if own:
            buffer.append(own)
        if tag in _BLOCK_TAGS and not _is_quote(node) and not _is_signature(node):
            buffer.append("\n")

        children = list(node.iter(include_text=False))
        for child in reversed(children):
            stack.append((child, nkind, ndepth, nattr))

    blocks.append((cur_kind, cur_depth, cur_attr, flush()))
    return blocks


def _is_quote(node) -> bool:
    if node.tag == "blockquote" and (
        node.attributes.get("type", "").strip().lower() == "cite"
    ):
        return True
    return "gmail_quote" in (node.attributes.get("class", "") or "").lower()


def _is_signature(node) -> bool:
    return "gmail_signature" in (node.attributes.get("class", "") or "").lower()


def _is_attr(node) -> bool:
    return "gmail_attr" in (node.attributes.get("class", "") or "").lower()


def _is_hidden(node) -> bool:
    style = (node.attributes.get("style", "") or "").lower().replace(" ", "")
    if "display:none" in style or "visibility:hidden" in style:
        return True
    if node.attributes.get("hidden") is not None:
        return True
    cls = (node.attributes.get("class", "") or "").lower()
    return "preheader" in cls
