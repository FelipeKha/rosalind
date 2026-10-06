"""Pure, deterministic chunking of a source text.

Splits a single source text into overlapping chunks at code-point boundaries,
greedy and side-effect free. The tokenizer is injected behind a ``TokenCounter``
port so this module stays free of any tokenizer dependency.

Splitting is three-level: paragraphs first (preferred chunk boundaries), then
sentences for an over-budget paragraph, then tokenizer offsets for an
over-budget sentence. Offsets are always code-point offsets, so a split can
never land in the middle of a surrogate pair.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from rosalind.domain.search.chunks import ChunkingParams, ChunkSpan
from rosalind.domain.search.tokens import TokenCounter

_SENTENCE_TERMINATORS = frozenset(".!?…。！？")


def _iter_lines(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` code-point offsets of each line (incl. newline)."""
    lines: list[tuple[int, int]] = []
    start = 0
    for line in text.splitlines(keepends=True):
        lines.append((start, start + len(line)))
        start += len(line)
    return lines


def _split_paragraphs(text: str) -> list[tuple[int, int]]:
    """Tile ``text`` into maximal non-blank-line runs.

    Blank-line runs are attached to the preceding paragraph so the paragraphs
    tile the text exactly (no bytes dropped).
    """
    paragraphs: list[tuple[int, int]] = []
    para_start: int | None = None
    para_end = 0
    for start, end in _iter_lines(text):
        line = text[start:end]
        if line.strip() == "":
            if para_start is not None:
                para_end = end
        else:
            if para_start is None:
                para_start = start
            para_end = end
    if para_start is not None:
        paragraphs.append((para_start, para_end))
    return paragraphs


def _split_sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split ``text[start:end]`` into sentences at terminators and newlines."""
    spans: list[tuple[int, int]] = []
    sentence_start = start
    i = start
    while i < end:
        ch = text[i]
        if ch in _SENTENCE_TERMINATORS or ch == "\n":
            i += 1
            while i < end and (text[i] in _SENTENCE_TERMINATORS or text[i] == "\n"):
                i += 1
            spans.append((sentence_start, i))
            sentence_start = i
        else:
            i += 1
    if sentence_start < end:
        spans.append((sentence_start, end))
    return spans


class _Unit:
    __slots__ = ("end", "start", "tokens")

    def __init__(self, start: int, end: int, tokens: int):
        self.start = start
        self.end = end
        self.tokens = tokens


def _build_units(
    text: str, counter: TokenCounter, params: ChunkingParams
) -> list[_Unit]:
    """Flatten the text into packable units that each fit within ``max_tokens``."""
    units: list[_Unit] = []
    for p_start, p_end in _split_paragraphs(text):
        if counter.count(text[p_start:p_end]) <= params.max_tokens:
            units.append(_Unit(p_start, p_end, counter.count(text[p_start:p_end])))
            continue
        for s_start, s_end in _split_sentences(text, p_start, p_end):
            if counter.count(text[s_start:s_end]) <= params.max_tokens:
                units.append(_Unit(s_start, s_end, counter.count(text[s_start:s_end])))
                continue
            piece = text[s_start:s_end]
            boundaries = counter.split_boundaries(piece, params.max_tokens)
            for lo, hi in pairwise(boundaries):
                units.append(
                    _Unit(s_start + lo, s_start + hi, counter.count(piece[lo:hi]))
                )
    return units


def _group(units: Sequence[_Unit], target_tokens: int) -> list[list[_Unit]]:
    """Greedily pack units into chunks up to ``target_tokens`` each."""
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    current_tokens = 0
    for unit in units:
        if current and current_tokens + unit.tokens > target_tokens:
            groups.append(current)
            current = [unit]
            current_tokens = unit.tokens
        else:
            current.append(unit)
            current_tokens += unit.tokens
    if current:
        groups.append(current)
    return groups


def _merge_tail(
    groups: list[list[_Unit]], min_tail_tokens: int, max_tokens: int
) -> list[list[_Unit]]:
    """Merge an undersized final chunk into the previous one when it fits."""
    if len(groups) < 2:
        return groups
    last = groups[-1]
    last_tokens = sum(unit.tokens for unit in last)
    if last_tokens >= min_tail_tokens:
        return groups
    prev = groups[-2]
    prev_tokens = sum(unit.tokens for unit in prev)
    if prev_tokens + last_tokens <= max_tokens:
        return groups[:-2] + [prev + last]
    return groups


def _overlap_tail(group: list[_Unit], overlap_tokens: int) -> list[_Unit]:
    """Trailing whole units of ``group`` whose tokens fit within the overlap."""
    selected: list[_Unit] = []
    total = 0
    for unit in reversed(group):
        if total + unit.tokens > overlap_tokens:
            break
        selected.append(unit)
        total += unit.tokens
    return list(reversed(selected))


def chunk_text(
    text: str, *, counter: TokenCounter, params: ChunkingParams
) -> tuple[ChunkSpan, ...]:
    """Split ``text`` into overlapping chunks; each chunk's text fits in
    ``max_tokens`` tokens (prefix excluded — the caller budgets the prefix).

    Overlap carries the last whole sentences of the previous chunk within
    ``overlap_tokens``, only between chunks of the same source, and only up to
    the room left before ``max_tokens``.
    """
    if not text:
        return ()

    units = _build_units(text, counter, params)
    groups = _group(units, params.target_tokens)
    groups = _merge_tail(groups, params.min_tail_tokens, params.max_tokens)

    spans: list[ChunkSpan] = []
    for idx, group in enumerate(groups):
        start = group[0].start
        if idx > 0 and params.overlap_tokens > 0:
            group_tokens = sum(unit.tokens for unit in group)
            available = params.max_tokens - group_tokens
            if available > 0:
                overlap = _overlap_tail(
                    groups[idx - 1], min(params.overlap_tokens, available)
                )
                if overlap:
                    start = overlap[0].start
        spans.append(ChunkSpan(seq=idx, start=start, end=group[-1].end))
    return tuple(spans)


def truncate_to_tokens(
    text: str, max_tokens: int, counter: TokenCounter
) -> tuple[str, bool]:
    """Keep the earliest part of ``text`` within ``max_tokens`` tokens.

    Returns ``(prefix, truncated)``; the cut is at a code-point (token) boundary.
    """
    if counter.count(text) <= max_tokens:
        return text, False
    boundaries = counter.split_boundaries(text, max_tokens)
    if len(boundaries) < 2:
        return text, True
    return text[: boundaries[1]], True
