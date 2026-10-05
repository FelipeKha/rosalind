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


def stream_pipeline(import_id: str) -> Iterator[dict[str, Any]]:
    """Run the offline pipeline and yield decoded progress events."""
    for line in http.api.stream_post(f"/imports/{import_id}/pipeline"):
        yield json.loads(line)
