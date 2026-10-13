"""Live search executor: runs questions through the app's real search service.

Implements the ``SearchExecutor`` port by driving the app's ``SearchService``
(Prepare + the one ``SearchPipeline``). Composition root injects the service and
the authenticated account; this adapter does no wiring of its own.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from rosalind.application.eval.cache import cached_run
from rosalind.application.eval.dataset import QuestionRecord
from rosalind.application.eval.mapping import (
    question_run_from_short_circuit,
    question_run_from_trace,
)
from rosalind.application.eval.models import QuestionRun
from rosalind.application.eval.ports import StageCache

__all__ = ["PipelineSearchExecutor"]


class PipelineSearchExecutor:
    """Runs questions against the app's ``SearchService``/``SearchPipeline``."""

    def __init__(
        self,
        service: Any,
        account_id: uuid.UUID,
        *,
        overrides: Any | None = None,
        mode: str | None = None,
        limit: int = 10,
        client_id: str = "rosalind-eval",
        cache: StageCache | None = None,
    ) -> None:
        self._service = service
        self._account_id = account_id
        self._overrides = overrides
        self._mode = mode
        self._limit = limit
        self._client_id = client_id
        self._cache = cache

    def execute(self, question: QuestionRecord) -> QuestionRun:
        from rosalind.application.search import (
            GroupBy,
            ResultView,
            SearchMode,
            SearchRequest,
            ShortCircuit,
            SortOrder,
        )
        from rosalind.application.services.search import PrepareContext

        request = SearchRequest(
            query=question.query,
            keywords=question.keywords,
            filters=question.filters.to_search_request_filters(),
            sort=SortOrder.RELEVANCE,
            group_by=GroupBy.MESSAGE,
            view=ResultView.METADATA,
            limit=self._limit,
            cursor=None,
            mode=SearchMode(self._mode) if self._mode else SearchMode.HYBRID,
        )
        context = PrepareContext(account_id=self._account_id, client_id=self._client_id)
        prepared = asyncio.run(self._service.prepare(context, request))
        if isinstance(prepared, ShortCircuit):
            return question_run_from_short_circuit(question, prepared)
        if self._cache is not None:
            trace, _ = asyncio.run(
                cached_run(
                    self._service.run,
                    prepared,
                    self._cache,
                    overrides=self._overrides,
                )
            )
            return question_run_from_trace(question, trace)
        trace = asyncio.run(
            self._service.run(prepared, trace_level="full", overrides=self._overrides)
        )
        return question_run_from_trace(question, trace)
