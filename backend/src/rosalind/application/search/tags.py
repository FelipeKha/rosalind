"""Tag and language canonicalization for the Prepare step.

Tags are provider-namespaced (``gmail:Projects``); stored tags preserve the
label's case, so a requested tag is matched case-insensitively against the
account's known vocabulary and, when it misses, a fuzzy suggestion is offered
("did you mean …?"). Unknown tags proceed with a warning rather than failing.
"""

from __future__ import annotations

from rapidfuzz import fuzz, process

__all__ = [
    "canonicalize_language",
    "canonicalize_tag",
]

_SUGGESTION_THRESHOLD = 80.0


def canonicalize_tag(
    requested: str, known_tags: frozenset[str]
) -> tuple[str, str | None]:
    """Return ``(resolved_tag, suggestion)``.

    ``resolved_tag`` is the vocabulary's canonical spelling on a
    case-insensitive match, otherwise the requested tag unchanged (unknown tags
    proceed with a warning). ``suggestion`` is set when a close match exists.
    """
    stripped = requested.strip()
    lowered = stripped.lower()
    by_lower = {tag.lower(): tag for tag in known_tags}
    if lowered in by_lower:
        return by_lower[lowered], None

    if known_tags:
        match = process.extractOne(stripped, known_tags, scorer=fuzz.ratio)
        if match is not None:
            best, score, _ = match
            if score >= _SUGGESTION_THRESHOLD:
                return stripped, best

    return stripped, None


def canonicalize_language(requested: str) -> str:
    """Lowercase and strip an ISO 639-1 language code."""
    return requested.strip().lower()
