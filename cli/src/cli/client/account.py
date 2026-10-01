"""Client for the current-account resource (``/me``)."""

from __future__ import annotations

from typing import Any

from cli.client import http


def whoami() -> dict[str, Any]:
    return http.api.get("/me")
