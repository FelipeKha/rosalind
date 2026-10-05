"""Canonical value normalization.

Normalization belongs to the canonicalization layer, not to provider adapters.
"""

from __future__ import annotations

import re

_NON_DIGITS = re.compile(r"\D")


def normalize_phone(phone: str) -> str:
    """Normalize a phone number for canonical matching.

    Strips whitespace and all non-digit characters except a leading ``+``. This
    yields a stable, provider-independent comparison key without claiming
    ITU-T E.164 equivalence; the original provider value (and Google's own
    ``canonicalForm``, where present) is preserved on the assertion/raw record.
    """
    stripped = phone.strip()
    prefix = "+" if stripped.startswith("+") else ""
    return prefix + _NON_DIGITS.sub("", stripped)
