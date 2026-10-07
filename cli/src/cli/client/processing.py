"""Client for the processing operations (``POST /imports/{id}/process`` and
the offline pipeline ``POST /imports/{id}/pipeline``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from cli.client import http


def process_import(import_id: str) -> dict[str, Any]:
    return http.api.post(f"/imports/{import_id}/process")


def stream_pipeline(
    import_id: str, stage: str | None = None
) -> Iterator[dict[str, Any]]:
    """Run the offline pipeline and yield decoded progress events."""
    path = f"/imports/{import_id}/pipeline"
    if stage:
        path = f"{path}?stage={stage}"
    for line in http.api.stream_post(path):
        yield json.loads(line)
