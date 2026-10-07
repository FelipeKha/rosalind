"""Lossless segmentation of a message's clean text.

Two strategies, chosen by the source representation:

- **HTML** (structure-first): consumes the adapter's ``HtmlDocument`` blocks and
  maps them to segments, splitting a ``body`` block on the ``--`` signature
  delimiter when no structural signature container exists.
- **Plain** (fallback): line scan marking ``>``-prefixed lines as quoted and a
  top-level ``--`` delimiter as the start of a signature.

Both are lossless: the returned segments tile the input text exactly. The
heuristics use linear scans, never backtracking regexes, so adversarial input
cannot cause catastrophic blow-up.
"""

from __future__ import annotations

from collections.abc import Iterator

from rosalind.domain.email.enrichment import EmailSegment, SegmentKind
from rosalind.domain.email.html import HtmlDocument

_SIGNATURE_MARKERS = ("--", "-- ")


def _iter_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(start_offset, line_including_newline)`` for each line."""
    start = 0
    for line in text.splitlines(keepends=True):
        yield start, line
        start += len(line)


def _classify_plain_line(body: str) -> tuple[str, int]:
    """Classify one plain line as ``('quoted', depth)``, ``('signature', 0)`` or
    ``('new', 0)``."""
    depth = 0
    index = 0
    length = len(body)
    while index < length:
        ch = body[index]
        if ch == ">":
            depth += 1
            index += 1
        elif ch in " \t":
            index += 1
        else:
            break
    if depth > 0:
        return "quoted", depth
    if body.strip() in _SIGNATURE_MARKERS:
        return "signature", 0
    return "new", 0


def segment_plain(clean_text: str) -> tuple[EmailSegment, ...]:
    """Tile ``clean_text`` into new/quoted/signature segments via line heuristics."""
    if not clean_text:
        return ()

    segments: list[EmailSegment] = []
    cur_kind: str | None = None
    cur_depth = 0
    cur_start = 0
    cur_end = 0
    in_signature = False

    for start, line in _iter_lines(clean_text):
        body = line.rstrip("\n")
        if in_signature:
            kind, depth = "signature", 0
        else:
            kind, depth = _classify_plain_line(body)
            if kind == "signature" and cur_kind is None:
                kind, depth = "new", 0
            elif kind == "signature":
                in_signature = True

        if cur_kind is None:
            cur_kind, cur_depth, cur_start = kind, depth, start
        elif kind != cur_kind or depth != cur_depth:
            segments.append(
                _segment(len(segments), cur_kind, cur_depth, cur_start, cur_end)
            )
            cur_kind, cur_depth, cur_start = kind, depth, start
        cur_end = start + len(line)

    if cur_kind is not None:
        segments.append(
            _segment(len(segments), cur_kind, cur_depth, cur_start, cur_end)
        )

    return tuple(segments)


def segment_html(doc: HtmlDocument) -> tuple[EmailSegment, ...]:
    """Map an ``HtmlDocument``'s structural blocks onto segments."""
    segments: list[EmailSegment] = []
    seq = 0
    for block in doc.blocks:
        if block.kind == "body":
            for sub in _split_signature(block, seq):
                segments.append(sub)
                seq += 1
        else:
            segments.append(
                EmailSegment(
                    seq=seq,
                    kind=_kind(block.kind),
                    start_offset=block.start,
                    end_offset=block.end,
                    quote_depth=block.quote_depth,
                    attribution_raw=block.attribution,
                )
            )
            seq += 1
    return tuple(segments)


def _split_signature(block, start_seq: int) -> list[EmailSegment]:
    """Split a body block at a ``--`` delimiter line, if one is present."""
    for line_start, line in _iter_lines(block.text):
        if line.rstrip("\n").strip() in _SIGNATURE_MARKERS and line_start > 0:
            boundary = block.start + line_start
            return [
                EmailSegment(
                    seq=start_seq,
                    kind=SegmentKind.NEW,
                    start_offset=block.start,
                    end_offset=boundary,
                    quote_depth=block.quote_depth,
                    attribution_raw=block.attribution,
                ),
                EmailSegment(
                    seq=start_seq + 1,
                    kind=SegmentKind.SIGNATURE,
                    start_offset=boundary,
                    end_offset=block.end,
                ),
            ]
    return [
        EmailSegment(
            seq=start_seq,
            kind=SegmentKind.NEW,
            start_offset=block.start,
            end_offset=block.end,
            quote_depth=block.quote_depth,
            attribution_raw=block.attribution,
        )
    ]


def _kind(kind: str) -> SegmentKind:
    return {
        "new": SegmentKind.NEW,
        "body": SegmentKind.NEW,
        "quoted": SegmentKind.QUOTED,
        "quote": SegmentKind.QUOTED,
        "signature": SegmentKind.SIGNATURE,
        "forwarded": SegmentKind.FORWARDED,
    }[kind]


def _segment(seq: int, kind: str, depth: int, start: int, end: int) -> EmailSegment:
    return EmailSegment(
        seq=seq,
        kind=_kind(kind),
        start_offset=start,
        end_offset=end,
        quote_depth=depth,
    )
