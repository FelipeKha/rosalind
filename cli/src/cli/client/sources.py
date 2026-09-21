"""Client for the source resource (``/sources``)."""

from __future__ import annotations

from typing import Any

from cli.client import http


def list_sources() -> list[dict[str, Any]]:
    return http.api.get("/sources")["sources"]


def get_source(source_id: str) -> dict[str, Any]:
    return http.api.get(f"/sources/{source_id}")


def create_source(provider: str, name: str) -> dict[str, Any]:
    return http.api.post("/sources", json={"provider": provider, "name": name})


def connect(provider: str, name: str | None = None) -> dict[str, Any]:
    return http.api.post("/sources/connect", json={"provider": provider, "name": name})


def connect_status(state: str) -> dict[str, Any]:
    return http.api.get("/sources/connect/status", params={"state": state})


def disconnect(source_id: str) -> dict[str, Any]:
    return http.api.post(f"/sources/{source_id}/disconnect")
