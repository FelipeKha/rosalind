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

from sqlalchemy.orm import Session

from rosalind.domain.models import PersonProfile
from rosalind.repositories.person_repository import PersonRepository

MAX_SEARCH_RESULTS = 25
MAX_LIST_RESULTS = 100


class PersonService:
    def __init__(self, repo: PersonRepository):
        self._repo = repo

    def search_people(self, db: Session, query: str) -> list[PersonProfile]:
        # Bounded responses by design: this is an AI-facing interface, so the
        # caller can never request an unbounded result set.
        return self._repo.search(db, query, limit=MAX_SEARCH_RESULTS)

    def list_people(self, db: Session) -> list[PersonProfile]:
        return self._repo.list_all(db, limit=MAX_LIST_RESULTS)

    def get_person(self, db: Session, person_id: uuid.UUID) -> PersonProfile | None:
        return self._repo.get(db, person_id)
