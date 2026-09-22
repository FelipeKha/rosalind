"""Canonical value normalization.

Normalization belongs to the canonicalization layer, not to provider adapters.
"""

from __future__ import annotations


def normalize_email(email: str) -> str:
    """Normalize an email address for canonical matching.

    Rosalind currently treats email addresses as case-insensitive for canonical
    matching: the value is stripped and lowercased. The original provider value
    is always preserved in ``core.person_email.email``. This is a Rosalind
    matching policy, not a claim about SMTP equivalence, and it deliberately
    does not apply provider-specific semantics such as Gmail dot/plus folding.
    """
    return email.strip().lower()
