"""Canonical value normalization.

Normalization belongs to the canonicalization layer, not to provider adapters.
"""

from __future__ import annotations


def normalize_name(name: str) -> str:
    """Normalize a person name for canonical matching.

    A deterministic, provider-independent comparison key: the value is stripped
    and lowercased. It is used only for resolution (e.g. matching an unresolved
    relation name to a canonical person); the original value is always preserved
    on the fact and assertion.
    """
    return name.strip().lower()
