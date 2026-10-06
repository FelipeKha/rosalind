"""Unit tests for the pg_search lexical query renderer.

The renderer turns the structured ``LexicalQuery`` (terms + phrases) into a
pg_search query string, escaping operator characters and quoting phrases. No
database is involved.
"""

from __future__ import annotations

from rosalind.adapters.outbound.search.lexical import ParadeDbLexicalQueryRenderer
from rosalind.application.search import LexicalQuery

renderer = ParadeDbLexicalQueryRenderer()


def test_terms_are_space_joined() -> None:
    assert renderer.render(LexicalQuery(terms=("roof", "quote"))) == "roof quote"


def test_phrases_are_quoted() -> None:
    assert renderer.render(LexicalQuery(phrases=("roof quote",))) == '"roof quote"'


def test_mixed_terms_and_phrases() -> None:
    query = LexicalQuery(terms=("invoice",), phrases=("12 Elm St",))
    assert renderer.render(query) == 'invoice "12 Elm St"'


def test_operator_characters_are_escaped() -> None:
    query = LexicalQuery(terms=("C++", "(quote", "2026-0412"))
    assert renderer.render(query) == r"C\+\+ \(quote 2026\-0412"


def test_embedded_quote_in_phrase_is_escaped() -> None:
    query = LexicalQuery(phrases=('say "hi"',))
    assert renderer.render(query) == r'"say \"hi\""'
