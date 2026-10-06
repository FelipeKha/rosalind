"""Online search: the Prepare entry point.

Phase 0 defines only the seam. ``prepare`` receives the authenticated account
and a plain ``SearchRequest`` (no framework types) and will, once phase 1 lands,
return a ``SearchPlan`` or ``ShortCircuit`` per
``docs/features/search_plan_schema.py``. Retrieval, fusion, rerank and assembly
are later phases and do not appear here.
"""

from __future__ import annotations

import uuid

from rosalind.application.search import SearchRequest


class SearchService:
    """Coordinates online email search, beginning with Prepare."""

    def prepare(self, account_id: uuid.UUID, request: SearchRequest) -> object:
        """Validate, resolve and build a search plan for ``request``.

        Not implemented yet: phase 1 (Prepare) fills this in and returns a
        ``SearchPlan`` / ``ShortCircuit``. The return type is updated then.
        """
        raise NotImplementedError("online search is not implemented yet")
