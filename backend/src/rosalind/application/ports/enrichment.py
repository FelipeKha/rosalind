"""Ports for the enrich stage's tools.

HTML parsing and language detection are CPU-bound outbound tools. The enrich
service depends on these Protocols, never on selectolax or lingua-py directly;
concrete adapters live in ``adapters.outbound.enrichment``. Each reports its
version so ``stage_version`` can invalidate the right rows when a library bumps.
"""

from __future__ import annotations

from typing import Protocol

from rosalind.domain.email.html import HtmlDocument


class HtmlParser(Protocol):
    version: str

    def parse(self, html: str) -> HtmlDocument:
        """Turn an ``text/html`` body into neutral structure for segmentation."""


class LanguageDetector(Protocol):
    version: str

    def detect(self, text: str) -> tuple[str | None, float | None]:
        """Return ``(iso_639_1, confidence)`` or ``(None, None)`` below threshold."""
