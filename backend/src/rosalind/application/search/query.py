"""Query-text preparation for the online search Prepare step.

Pure functions with no I/O. They turn the raw ``query`` / ``keywords`` strings
into the structured ``LexicalQuery`` (terms + phrases) and the cleaned
``semantic_text`` the embedding model receives. Engine syntax (ParadeDB / pg_search)
is *not* produced here: the outbound retrieval adapter renders ``LexicalQuery``
into whatever syntax the installed engine version needs and does the escaping
there (see ``docs/features/search_plan_schema.py``).
"""

from __future__ import annotations

import re
import unicodedata

from rosalind.application.search.plan import LexicalQuery

__all__ = [
    "normalize_semantic_text",
    "parse_keywords",
]

# A quoted phrase (double or single quotes) or a bare whitespace-delimited token.
_TOKEN_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')


def normalize_semantic_text(text: str) -> str:
    """Normalize a query for the embedding model: NFKC + collapsed whitespace.

    Casing is preserved (the embedding model is case-sensitive); only Unicode
    compatibility and whitespace are normalized.
    """
    return _collapse(unicodedata.normalize("NFKC", text))


def parse_keywords(text: str) -> LexicalQuery | None:
    """Split keyword text into ``LexicalQuery`` terms and quoted phrases.

    Quoted spans (double or single quotes) become phrases with the quotes
    stripped; the rest are whitespace-delimited terms. Returns ``None`` when
    there is no content, so a keyword string with only whitespace behaves like
    no keyword constraint.
    """
    terms: list[str] = []
    phrases: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        double, single, bare = match.groups()
        if double is not None:
            phrase = _collapse(double)
            if phrase:
                phrases.append(phrase)
        elif single is not None:
            phrase = _collapse(single)
            if phrase:
                phrases.append(phrase)
        elif bare is not None:
            terms.append(bare)
    if not terms and not phrases:
        return None
    return LexicalQuery(terms=tuple(terms), phrases=tuple(phrases))


def _collapse(text: str) -> str:
    return " ".join(text.split())
