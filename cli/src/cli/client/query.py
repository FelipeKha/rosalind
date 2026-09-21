"""Client for the person query resource (``/people``)."""

from __future__ import annotations

from typing import Any

from cli.client import http


def list_people() -> list[dict[str, Any]]:
    return http.api.get("/people")


def search_people(query: str) -> list[dict[str, Any]]:
    return http.api.get("/people/search", params={"q": query})


def get_person(person_id: str) -> dict[str, Any]:
    return http.api.get(f"/people/{person_id}")
