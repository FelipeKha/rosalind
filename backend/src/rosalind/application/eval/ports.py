"""Ports for the eval subsystem.

Protocols the eval application layer depends on. Concrete implementations live
in ``rosalind.adapters.outbound.eval`` (search execution, run storage, item
catalog, question LLM, mailbox passages, stage cache) and the inbound HTTP
adapter in ``rosalind.adapters.inbound.http.routes.eval``.
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
from rosalind.application.search.fusion import FusedCandidates
from rosalind.application.search.rerank import RerankResult
from rosalind.application.search.retrieve import LexicalResult
from rosalind.application.search.semantic import SemanticResult

__all__ = [
    "EvalRunStore",
    "ItemCatalog",
    "PassageSource",
    "QuestionLLM",
    "SearchExecutor",
    "SearchExecutorFactory",
    "StageCache",
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


class StageCache(Protocol):
    def get_lexical(self, key: str) -> LexicalResult | None: ...

    def get_semantic(self, key: str) -> SemanticResult | None: ...

    def get_fused(self, key: str) -> FusedCandidates | None: ...

    def get_reranked(self, key: str) -> RerankResult | None: ...

    def put_lexical(self, key: str, value: LexicalResult | None) -> None: ...

    def put_semantic(self, key: str, value: SemanticResult | None) -> None: ...

    def put_fused(self, key: str, value: FusedCandidates | None) -> None: ...

    def put_reranked(self, key: str, value: RerankResult | None) -> None: ...
