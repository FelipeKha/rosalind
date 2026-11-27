"""Unit tests for the pure segmentation and cut-plus-marker primitives."""

from __future__ import annotations

from itertools import pairwise

from rosalind.domain.semantic import (
    MARKER,
    Span,
    merge_spans,
    sanitize,
    segment_text,
    text_hash,
)


def test_segmentation_offsets_are_exact_and_ordered() -> None:
    text = "Hello world. Second sentence! Third?"
    segments = segment_text(text)
    assert [segment.text for segment in segments] == [
        "Hello world.",
        "Second sentence!",
        "Third?",
    ]
    for segment in segments:
        assert text[segment.start : segment.end] == segment.text
    assert segments[0].start == 0
    assert all(a.end <= b.start for a, b in pairwise(segments))


def test_segmentation_handles_newlines_and_empty_input() -> None:
    assert [segment.text for segment in segment_text("one\n\ntwo")] == ["one", "two"]
    assert segment_text("   ") == ()


def test_text_hash_normalizes_case_whitespace_and_quote_prefix() -> None:
    assert text_hash("I have cancer") == text_hash("   i   HAVE  cancer ")
    assert text_hash("I have cancer") == text_hash("> I have cancer")


def test_sanitize_cuts_span_and_keeps_rest_visible() -> None:
    text = "I have cancer, let's meet tomorrow at 10am."
    result = sanitize(text, [Span(0, 13)])  # "I have cancer"
    assert result.display_text == f"{MARKER}, let's meet tomorrow at 10am."
    assert result.index_text == "let's meet tomorrow at 10am."
    assert result.redacted
    redaction = result.redactions[0]
    assert result.display_text[redaction.start : redaction.end] == MARKER


def test_sanitize_with_no_spans_is_identity() -> None:
    text = "Nothing protected here."
    result = sanitize(text, [])
    assert result.display_text == text
    assert result.index_text == text
    assert not result.redacted


def test_overlapping_and_adjacent_spans_merge_to_one_marker() -> None:
    text = "My cancer is bad."
    merged = merge_spans([Span(3, 9), Span(3, 10), Span(10, 13)], len(text))
    assert merged == (Span(3, 13),)
    result = sanitize(text, list(merged))
    assert result.display_text.count(MARKER) == 1


def test_spans_are_clamped_to_text_length() -> None:
    text = "short"
    merged = merge_spans([Span(2, 100)], len(text))
    assert merged == (Span(2, 5),)


def test_sanitize_snaps_to_word_boundaries() -> None:
    text = "foo cancer bar"
    # A span that starts/ends mid-word is expanded to whole words.
    result = sanitize(text, [Span(5, 9)])
    assert result.display_text == f"foo {MARKER} bar"


def test_index_text_does_not_contain_the_marker() -> None:
    text = "I have cancer, let's meet."
    result = sanitize(text, [Span(0, 13)])
    assert MARKER not in result.index_text
    assert "redacted" not in result.index_text.lower()
