"""Tests for backend settings defaults."""

from __future__ import annotations

from pathlib import Path

from rosalind.config import Settings


def test_default_chunk_tokenizer_path_is_absolute_and_exists(monkeypatch) -> None:
    """The tokenizer default must not depend on the process CWD.

    The serve recipes run uvicorn with CWD=``backend/``, so a repo-relative
    default would resolve to ``backend/backend/assets/...`` and fail at runtime.
    """
    monkeypatch.delenv("ROSALIND_CHUNK_TOKENIZER_PATH", raising=False)
    path = Path(Settings().chunk_tokenizer_path)
    assert path.is_absolute()
    assert path.is_file()
