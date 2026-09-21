"""Client for the import resource (``/imports``)."""

from __future__ import annotations

from typing import Any

from cli.client import http


def create_import(source_name: str, type_: str) -> dict[str, Any]:
    return http.api.post("/imports", json={"source_name": source_name, "type": type_})


def complete_import(import_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    return http.api.post(f"/imports/{import_id}/complete", json=manifest)


def list_imports() -> list[dict[str, Any]]:
    return http.api.get("/imports")["imports"]


def get_import(import_id: str) -> dict[str, Any]:
    return http.api.get(f"/imports/{import_id}")


def delete_import(import_id: str) -> None:
    http.api.delete(f"/imports/{import_id}")
