"""Ports for the eval subsystem.

Protocols the eval application layer depends on. Concrete implementations live
in ``rosalind.adapters.outbound.eval`` (search execution, run storage, item
catalog, question LLM, mailbox passages) and the inbound HTTP adapter in
``rosalind.adapters.inbound.http.routes.eval``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from rosalind.application.eval.dataset import QuestionRecord
from rosalind.application.eval.models import (
    DraftQuestion,
    ItemSummary,
    Passage,
    QuestionRun,
)

__all__ = [
    "EvalRunStore",
    "ItemCatalog",
    "PassageSource",
    "QuestionLLM",
    "SearchExecutor",
    "SearchExecutorFactory",
]


class SearchExecutor(Protocol):
    def execute(self, question: QuestionRecord) -> QuestionRun:
        """Run the search pipeline for one question."""


class SearchExecutorFactory(Protocol):
    def __call__(self, *, overrides: Any | None, mode: str | None) -> SearchExecutor:
        """Build a search executor for one experiment's overrides."""


class EvalRunStore(Protocol):
    def write(
        self,
        *,
        manifest: dict[str, Any],
        question_rows: list[dict[str, Any]],
        stage_hit_rows: list[dict[str, Any]],
        metrics: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> str:
        """Persist a run's artifacts and return its run id."""

    def read_manifest(self, run_id: str) -> dict[str, Any]: ...

    def read_metrics(self, run_id: str) -> dict[str, Any]: ...

    def read_question_rows(self, run_id: str) -> list[dict[str, Any]]: ...

    def read_stage_hits(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_run_ids(self) -> list[str]: ...

    def location(self, run_id: str) -> str:
        """A human-readable location for a run (path or URI)."""


class ItemCatalog(Protocol):
    def list_items(
        self, account_id: uuid.UUID, import_id: uuid.UUID | None = None
    ) -> list[ItemSummary]:
        """List keyable corpus items for manual gold authoring."""

    def existing_item_ids(
        self, account_id: uuid.UUID, item_ids: frozenset[str]
    ) -> frozenset[str]:
        """The subset of ``item_ids`` that exist in this account's corpus."""


class QuestionLLM(Protocol):
    def generate(self, passage: Passage) -> DraftQuestion:
        """Write one question answerable by ``passage``."""


class PassageSource(Protocol):
    def iter_passages(
        self, mailbox: str | Path, *, include_trash_spam: bool = False
    ) -> Iterator[Passage]:
        """Yield one passage per message in a mailbox archive."""
