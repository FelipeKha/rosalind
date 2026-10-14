"""Client for the email search resource (``/search``)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from cli.client import http


def search(
    query: str | None = None,
    *,
    keywords: str | None = None,
    sender: Sequence[str] | None = None,
    since: date | None = None,
    before: date | None = None,
    has_attachment: bool | None = None,
    mode: str = "hybrid",
    limit: int = 10,
    cursor: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"mode": mode, "limit": limit}
    if query is not None:
        payload["query"] = query
    if keywords is not None:
        payload["keywords"] = keywords
    if cursor is not None:
        payload["cursor"] = cursor

    filters: dict[str, Any] = {}
    if sender:
        filters["sender"] = list(sender)
    if since is not None:
        filters["date_from"] = since.isoformat()
    if before is not None:
        filters["date_before"] = before.isoformat()
    if has_attachment is not None:
        filters["has_attachment"] = has_attachment
    if filters:
        payload["filters"] = filters

    return http.api.post("/search", json=payload)
