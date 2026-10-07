from rosalind.domain.email.enrichment import content_sha256
from rosalind.domain.email.html import HtmlBlock, HtmlDocument
from rosalind.domain.email.segmentation import segment_html, segment_plain
from rosalind.domain.email.text import clean_plain, is_mostly_urls, select_clean_text


def test_content_sha256_is_deterministic() -> None:
    assert content_sha256("a", "b") == content_sha256("a", "b")


def test_content_sha256_length_prefixes_prevent_boundary_ambiguity() -> None:
    assert content_sha256("a", "bc") != content_sha256("ab", "c")


def test_content_sha256_none_equals_empty() -> None:
    assert content_sha256(None, "x") == content_sha256("", "x")
    assert content_sha256("x", None) == content_sha256("x", "")


def test_clean_plain_strips_nul_and_control_characters() -> None:
    assert clean_plain("a\x00b\x01c\x7fd") == "abcd"


def test_clean_plain_preserves_newlines_and_tabs() -> None:
    assert clean_plain("a\tb\nc") == "a\tb\nc"


def test_clean_plain_normalizes_line_endings_and_nfc() -> None:
    assert clean_plain("a\r\nb\rc") == "a\nb\nc"


def test_clean_plain_collapses_spaces_within_a_line() -> None:
    assert clean_plain("a    b") == "a b"


def test_clean_plain_preserves_signature_delimiter_trailing_space() -> None:
    assert clean_plain("body\n-- \nsig") == "body\n-- \nsig"


def test_segment_plain_tiles_clean_text_exactly() -> None:
    text = "Hello\n> quoted\n> > deeper\nThanks\n-- \nSig\n"
    segments = segment_plain(text)
    assert "".join(text[s.start_offset : s.end_offset] for s in segments) == text


def test_segment_plain_classifies_quote_depth_and_signature() -> None:
    text = "Hello\n> quoted\n> > deeper\n-- \nSig\n"
    segments = segment_plain(text)
    kinds = [(s.kind.value, s.quote_depth) for s in segments]
    assert kinds == [
        ("new", 0),
        ("quoted", 1),
        ("quoted", 2),
        ("signature", 0),
    ]


def test_segment_plain_leading_delimiter_is_not_signature() -> None:
    segments = segment_plain("-- \nbody\n")
    assert all(s.kind.value != "signature" for s in segments)


def test_segment_plain_empty_is_no_segments() -> None:
    assert segment_plain("") == ()


def test_segment_html_maps_blocks_and_splits_signature() -> None:
    doc = HtmlDocument(
        text="Thanks\n-- \nSig\n",
        blocks=(HtmlBlock(kind="body", text="Thanks\n-- \nSig\n", start=0, end=15),),
        has_quote_structure=False,
    )
    segments = segment_html(doc)
    assert [s.kind.value for s in segments] == ["new", "signature"]
    assert (
        "".join(doc.text[s.start_offset : s.end_offset] for s in segments) == doc.text
    )


def test_segment_html_preserves_quote_depth_and_attribution() -> None:
    doc = HtmlDocument(
        text="new\nquote\n",
        blocks=(
            HtmlBlock(kind="body", text="new\n", start=0, end=4),
            HtmlBlock(
                kind="quote",
                text="quote\n",
                start=4,
                end=10,
                quote_depth=2,
                attribution="On Tue wrote:",
            ),
        ),
        has_quote_structure=True,
    )
    segments = segment_html(doc)
    quoted = [s for s in segments if s.kind.value == "quoted"]
    assert len(quoted) == 1
    assert quoted[0].quote_depth == 2
    assert quoted[0].attribution_raw == "On Tue wrote:"


def test_is_mostly_urls_detects_stub() -> None:
    assert is_mostly_urls("https://a.com https://b.com https://c.com")
    assert not is_mostly_urls("hello world")


def test_select_clean_text_prefers_html_structure() -> None:
    doc = HtmlDocument(
        text="html body",
        blocks=(HtmlBlock(kind="body", text="html body\n", start=0, end=10),),
        has_quote_structure=True,
    )
    text, method = select_clean_text("plain body", doc)
    assert method == "html"
    assert text == "html body"


def test_select_clean_text_uses_plain_when_no_quote_structure() -> None:
    doc = HtmlDocument(
        text="html body",
        blocks=(HtmlBlock(kind="body", text="html body\n", start=0, end=10),),
        has_quote_structure=False,
    )
    text, method = select_clean_text("plain body", doc)
    assert method == "plain"
    assert text == "plain body"


def test_select_clean_text_falls_back_to_html_on_stub_plain() -> None:
    doc = HtmlDocument(
        text="a" * 500,
        blocks=(HtmlBlock(kind="body", text="a" * 500 + "\n", start=0, end=501),),
        has_quote_structure=False,
    )
    text, method = select_clean_text("https://view.in.browser", doc)
    assert method == "html"
    assert text == "a" * 500


def test_select_clean_text_returns_empty_when_no_input() -> None:
    text, method = select_clean_text(None, None)
    assert text == ""
    assert method == "plain"
