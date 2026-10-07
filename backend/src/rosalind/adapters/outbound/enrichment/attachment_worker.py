"""Subprocess entry point for isolated attachment text extraction.

The service runs this as ``python -m rosalind.adapters.outbound.enrichment.
attachment_worker <path> <blob_sha256> <detected_mime> <declared_mime> <filename>
<max_output_chars>``, where ``-`` means "no value". Blob bytes are read from the
temporary file at ``<path>`` (never passed through pickling), and the result is
printed as a single line of JSON. The parent enforces timeout and memory limits.
"""

from __future__ import annotations

import json
import sys

from rosalind.adapters.outbound.enrichment.attachments import extract_blob
from rosalind.domain.email import AttachmentText


def _optional(value: str) -> str | None:
    return None if value == "-" else value


def _to_dict(result: AttachmentText) -> dict[str, object]:
    return {
        "blob_sha256": result.blob_sha256,
        "status": result.status.value,
        "text": result.text,
        "method": result.method,
        "page_count": result.page_count,
        "language": result.language,
        "error": result.error,
        "truncated": result.truncated,
    }


def main(argv: list[str]) -> int:
    path, blob_sha256, detected, declared, filename, max_chars = argv[1:7]
    with open(path, "rb") as handle:
        data = handle.read()
    result = extract_blob(
        blob_sha256=blob_sha256,
        data=data,
        detected_mime=_optional(detected),
        declared_mime=_optional(declared),
        filename=_optional(filename),
        max_output_chars=int(max_chars),
    )
    print(json.dumps(_to_dict(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
