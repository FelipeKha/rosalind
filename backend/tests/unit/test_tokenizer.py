"""Unit tests for the bge-m3 tokenizer adapter (``BgeM3TokenCounter``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rosalind.adapters.outbound.search.tokenizer import BgeM3TokenCounter

ASSET = Path(__file__).resolve().parents[2] / "assets" / "bge-m3" / "tokenizer.json"


@pytest.mark.skipif(not ASSET.exists(), reason="tokenizer asset not bundled")
def test_token_counter_loads_bundled_asset() -> None:
    counter = BgeM3TokenCounter(str(ASSET), None)

    assert counter.count("hello world") == 3
    assert counter.version.startswith("bge-m3/")


def test_sha256_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "tokenizer.json"
    path.write_bytes(b"not a tokenizer")

    counter = BgeM3TokenCounter(str(path), "0" * 64)
    with pytest.raises(RuntimeError, match="does not match"):
        counter.count("hello")
