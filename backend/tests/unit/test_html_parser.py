from rosalind.adapters.outbound.enrichment.html import SelectolaxHtmlParser


def test_detects_gmail_quote_and_attribution() -> None:
    html = (
        '<div dir="ltr">Hi Alex,<br>Here is the quote.</div>'
        '<div class="gmail_quote">'
        '<div class="gmail_attr" dir="ltr">On Tue wrote:<br></div>'
        '<blockquote class="gmail_quote">Can you confirm the price?</blockquote>'
        "</div>"
    )
    doc = SelectolaxHtmlParser().parse(html)

    assert doc.has_quote_structure is True
    assert "Hi Alex" in doc.text
    assert "Can you confirm the price?" in doc.text
    quoted = [b for b in doc.blocks if b.kind == "quote"]
    assert any(b.attribution == "On Tue wrote:" for b in quoted)


def test_detects_apple_mail_blockquote_cite() -> None:
    html = (
        '<div>Hi</div><blockquote type="cite"><div>Original message</div></blockquote>'
    )
    doc = SelectolaxHtmlParser().parse(html)
    assert doc.has_quote_structure is True
    assert any(b.kind == "quote" for b in doc.blocks)


def test_detects_gmail_signature_container() -> None:
    html = (
        "<div>Best regards,</div>"
        '<div class="gmail_signature">Mike Turner<br>Turner Roofing</div>'
    )
    doc = SelectolaxHtmlParser().parse(html)
    assert any(b.kind == "signature" for b in doc.blocks)
    assert "Mike Turner" in doc.text


def test_drops_script_style_and_head() -> None:
    html = (
        "<html><head><style>body{color:red}</style></head><body>"
        "<script>var x=1;</script>Hello</body></html>"
    )
    doc = SelectolaxHtmlParser().parse(html)
    assert "var x=1" not in doc.text
    assert "body{color:red}" not in doc.text
    assert "Hello" in doc.text


def test_drops_hidden_preheader() -> None:
    html = '<div style="display:none">hidden preheader</div><div>visible body</div>'
    doc = SelectolaxHtmlParser().parse(html)
    assert "hidden preheader" not in doc.text
    assert "visible body" in doc.text


def test_html_only_message_without_quote_structure() -> None:
    html = "<div><p>Hello world</p><p>Second paragraph</p></div>"
    doc = SelectolaxHtmlParser().parse(html)
    assert doc.has_quote_structure is False
    assert "Hello world" in doc.text
    assert "Second paragraph" in doc.text


def test_deeply_nested_html_does_not_overflow() -> None:
    html = "<div>" * 5000 + "deep" + "</div>" * 5000
    doc = SelectolaxHtmlParser().parse(html)
    assert "deep" in doc.text


def test_empty_html() -> None:
    doc = SelectolaxHtmlParser().parse("")
    assert doc.text == ""
    assert doc.has_quote_structure is False
