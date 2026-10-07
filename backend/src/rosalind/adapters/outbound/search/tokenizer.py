"""bge-m3 tokenizer backed by the HF ``tokenizers`` library.

Loads a pinned, locally bundled tokenizer file and verifies its SHA-256 before
first use, failing hard on a mismatch. The tokenizer is loaded lazily so the
adapter can be wired at composition time without the asset present; the chunk
stage (and ``index_version``) trigger the load and verification.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

_TOKENIZER_MODEL = "bge-m3"


class BgeM3TokenCounter:
    """Token counter and code-point splitter for the bge-m3 tokenizer."""

    def __init__(self, tokenizer_path: str, expected_sha256: str | None):
        self._path = Path(tokenizer_path)
        self._expected_sha256 = expected_sha256
        self._tokenizer: Any = None
        self._file_sha256: str | None = None

    def _ensure_loaded(self) -> None:
        if self._tokenizer is not None:
            return
        data = self._path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if self._expected_sha256 is not None and digest != self._expected_sha256:
            raise RuntimeError(
                f"tokenizer file {self._path} sha256 {digest} does not match "
                f"expected {self._expected_sha256}"
            )
        from tokenizers import Tokenizer  # imported lazily so wiring needs no asset

        tokenizer_cls: Any = Tokenizer
        self._tokenizer = tokenizer_cls.from_bytes(data)
        self._file_sha256 = digest

    @property
    def version(self) -> str:
        """Token counter identity for ``index_version`` (includes the file hash)."""
        self._ensure_loaded()
        sha = self._file_sha256
        if sha is None:  # pragma: no cover - only possible if load failed silently
            raise RuntimeError("tokenizer file hash unavailable")
        return f"{_TOKENIZER_MODEL}/{sha[:16]}"

    def count(self, text: str) -> int:
        self._ensure_loaded()
        if not text:
            return 0
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        """Greedily split ``text`` into runs of at most ``max_tokens`` tokens.

        Boundaries are code-point offsets into ``text``; the bge-m3 (XLM-R /
        SentencePiece) tokenizer reports character offsets, which map directly
        to Python string indices.
        """
        self._ensure_loaded()
        if not text:
            return [0]
        encoding = self._tokenizer.encode(text, add_special_tokens=False)
        ids = encoding.ids
        offsets = encoding.offsets
        if not ids:
            return [0, len(text)]

        boundaries = [0]
        acc = 0
        for i, token_id in enumerate(ids):
            acc += 1
            if acc >= max_tokens and i + 1 < len(ids):
                boundary = offsets[i][1] if offsets else len(text)
                if boundary > boundaries[-1]:
                    boundaries.append(boundary)
                acc = 0
        if boundaries[-1] != len(text):
            boundaries.append(len(text))
        return boundaries
