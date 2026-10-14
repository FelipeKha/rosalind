"""Client for the processing operations (``POST /imports/{id}/process`` and
the offline indexing ``POST /imports/{id}/index``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from cli.client import http


def process_import(import_id: str) -> dict[str, Any]:
    return http.api.post(f"/imports/{import_id}/process")


def stream_index(import_id: str, stage: str | None = None) -> Iterator[dict[str, Any]]:
    """Run the offline indexing and yield decoded progress events."""
    path = f"/imports/{import_id}/index"
    if stage:
        path = f"{path}?stage={stage}"
    for line in http.api.stream_post(path):
        yield json.loads(line)
