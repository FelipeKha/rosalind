"""Client for the processing operation (``POST /imports/{id}/process``)."""

from __future__ import annotations

from typing import Any

from cli.client import http


def process_import(import_id: str) -> dict[str, Any]:
    return http.api.post(f"/imports/{import_id}/process")
