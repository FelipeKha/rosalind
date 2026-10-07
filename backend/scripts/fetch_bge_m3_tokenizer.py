"""Fetch and pin the bge-m3 tokenizer asset.

Downloads ``tokenizer.json`` for BAAI/bge-m3 (MIT licensed), writes it to the
asset directory, and prints its SHA-256 so it can be recorded in configuration.

Usage:
    uv run python -m scripts.fetch_bge_m3_tokenizer [--out backend/assets/bge-m3/tokenizer.json]
"""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path

HF_URL = "https://huggingface.co/BAAI/bge-m3/resolve/main/tokenizer.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default="backend/assets/bge-m3/tokenizer.json", help="destination path"
    )
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(HF_URL) as resp:
        data = resp.read()

    out.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f"wrote {out} ({len(data)} bytes)")
    print(f"sha256: {digest}")
    print("license: MIT (BAAI/bge-m3)")


if __name__ == "__main__":
    main()
