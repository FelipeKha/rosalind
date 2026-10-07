from dataclasses import replace

from rosalind.domain.search import ChunkingParams, chunk_text, truncate_to_tokens


class _CharCounter:
    """One token per character; splits at code-point boundaries."""

    version = "char/1"

    def count(self, text: str) -> int:
        return len(text)

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        boundaries = list(range(0, len(text), max_tokens))
        boundaries.append(len(text))
        return boundaries


def _params(**overrides) -> ChunkingParams:
    params = ChunkingParams(
        target_tokens=10,
        max_tokens=16,
        overlap_tokens=4,
        min_tail_tokens=3,
        max_quote_tokens_per_email=100,
        max_chunks_per_attachment=10,
        include_signature=True,
    )
    return replace(params, **overrides)


def _text(spans, source: str) -> list[str]:
    return [source[s.start : s.end] for s in spans]


def _own_text(spans, source: str) -> str:
    """Reconstruct the non-overlap content and assert it equals the source."""
    parts = []
    for i, span in enumerate(spans):
        own_start = span.start if i == 0 else spans[i - 1].end
        parts.append(source[own_start : span.end])
    return "".join(parts)


def test_every_chunk_within_max_tokens() -> None:
    counter = _CharCounter()
    params = _params()
    source = "alpha beta gamma\n\ndelta epsilon zeta\n\neta theta"
    spans = chunk_text(source, counter=counter, params=params)
    assert spans
    for chunk in _text(spans, source):
        assert counter.count(chunk) <= params.max_tokens


def test_deterministic_output() -> None:
    counter = _CharCounter()
    params = _params()
    source = "one two three.\nfour five six seven eight.\nnine ten."
    first = chunk_text(source, counter=counter, params=params)
    second = chunk_text(source, counter=counter, params=params)
    assert first == second


def test_no_text_loss_when_overlap_removed() -> None:
    counter = _CharCounter()
    params = _params(overlap_tokens=8)
    source = (
        "The quick brown fox jumps.\n"
        "Over the lazy dog.\n"
        "Pack my box with five dozen.\n"
        "Liquor jugs.\n"
        "Sphinx of black quartz.\n"
        "Judge my vow."
    )
    spans = chunk_text(source, counter=counter, params=params)
    assert len(spans) > 1
    assert _own_text(spans, source) == source


def test_cjk_without_spaces() -> None:
    counter = _CharCounter()
    params = _params(target_tokens=8, max_tokens=12)
    source = (
        "这是一封中文邮件。它没有任何空格。我们需要把它分块。每个块都要在预算之内。"
    )
    spans = chunk_text(source, counter=counter, params=params)
    assert spans
    assert _own_text(spans, source) == source
    for chunk in _text(spans, source):
        assert counter.count(chunk) <= params.max_tokens


def test_very_long_single_line() -> None:
    counter = _CharCounter()
    params = _params(max_tokens=10)
    source = "x" * 250  # no terminators, no newlines
    spans = chunk_text(source, counter=counter, params=params)
    assert len(spans) > 1
    assert _own_text(spans, source) == source
    for chunk in _text(spans, source):
        assert counter.count(chunk) <= params.max_tokens


def test_very_long_paragraph_split_by_sentences() -> None:
    counter = _CharCounter()
    params = _params(target_tokens=12, max_tokens=16)
    # A single paragraph of many sentences (no blank lines).
    source = ". ".join(f"word{i}" for i in range(40)) + "."
    spans = chunk_text(source, counter=counter, params=params)
    assert _own_text(spans, source) == source
    for chunk in _text(spans, source):
        assert counter.count(chunk) <= params.max_tokens


def test_empty_text_yields_no_chunks() -> None:
    counter = _CharCounter()
    assert chunk_text("", counter=counter, params=_params()) == ()


def test_truncate_to_tokens_keeps_earliest() -> None:
    counter = _CharCounter()
    text, truncated = truncate_to_tokens("abcdefghij", 4, counter)
    assert truncated is True
    assert text == "abcd"


def test_truncate_to_tokens_within_budget_is_unchanged() -> None:
    counter = _CharCounter()
    text, truncated = truncate_to_tokens("abc", 4, counter)
    assert truncated is False
    assert text == "abc"
