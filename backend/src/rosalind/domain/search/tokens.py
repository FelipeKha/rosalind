"""Token-counting port the pure chunking logic depends on.

Defined here (not in ``application.ports``) because the pure chunker needs it:
``domain`` must not import from ``application``. Concrete tokenizers (the bge-m3
adapter) satisfy this Protocol structurally.
"""

from __future__ import annotations

from typing import Protocol


class TokenCounter(Protocol):
    """Counts tokens and splits at code-point token boundaries."""

    @property
    def version(self) -> str:
        """Token counter identity, included in ``index_version``."""

    def count(self, text: str) -> int:
        """Number of tokens in ``text``."""

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        """Greedily split ``text`` into maximal token runs of at most
        ``max_tokens`` tokens. Returns code-point boundary offsets including
        ``0`` and ``len(text)``, so splitting there can never split a code point.
        """
