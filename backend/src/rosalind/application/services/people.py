"""Application service for the person read model.

The single seam both the REST API and the MCP server call. Contains no SQL and
no transport concerns; those live in ``PersonRepository`` and the adapters
respectively. Future write policy (e.g. an ``Actor`` that governs which writes
an agent may make) lands here, exactly once.

``search_people`` is deliberately narrow: it looks up *people* by name or
email. It is not a general personal-data retrieval mechanism.
"""

from __future__ import annotations

import uuid

from rosalind.application.ports.repositories import PersonRepository
from rosalind.application.read_models import PersonProfile

MAX_SEARCH_RESULTS = 25
MAX_LIST_RESULTS = 100


class PersonService:
    def __init__(self, repo: PersonRepository):
        self._repo = repo

    def search_people(self, query: str) -> list[PersonProfile]:
        # Bounded responses by design: this is an AI-facing interface, so the
        # caller can never request an unbounded result set.
        return self._repo.search(query, limit=MAX_SEARCH_RESULTS)

    def list_people(self) -> list[PersonProfile]:
        return self._repo.list_all(limit=MAX_LIST_RESULTS)

    def get_person(self, person_id: uuid.UUID) -> PersonProfile | None:
        return self._repo.get(person_id)
