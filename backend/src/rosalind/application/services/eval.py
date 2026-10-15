"""Eval use cases.

``EvalService`` composes the eval ports and the pure eval logic into the
operations the inbound HTTP/CLI surface exposes: run an experiment, compare two
runs, validate a dataset, list keyable items, and generate draft questions. It
depends only on the eval ports (never on concrete adapters).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

from rosalind.application.eval.compare import MetricDelta, RunSummary, compare_runs
from rosalind.application.eval.config import ExperimentConfig
from rosalind.application.eval.dataset import QuestionRecord, Split
from rosalind.application.eval.generate import generate_questions
from rosalind.application.eval.models import ItemSummary, RunOutcome
from rosalind.application.eval.ports import (
    EvalRunStore,
    ItemCatalog,
    PassageSource,
    QuestionLLM,
    SearchExecutor,
    SearchExecutorFactory,
)
from rosalind.application.eval.resolve import resolve_gold
from rosalind.application.eval.runner import iter_experiment, run_experiment
from rosalind.application.eval.validate import ValidationIssue, validate_dataset

__all__ = ["EvalService"]


class EvalService:
    """Runs and inspects search evaluations."""

    def __init__(
        self,
        *,
        search_factory: SearchExecutorFactory,
        run_store: EvalRunStore,
        item_catalog: ItemCatalog,
        account_id: uuid.UUID,
        passage_source: PassageSource | None = None,
        llm: QuestionLLM | None = None,
    ) -> None:
        self._search_factory = search_factory
        self._run_store = run_store
        self._item_catalog = item_catalog
        self._account_id = account_id
        self._passage_source = passage_source
        self._llm = llm

    def _executor(self, config: ExperimentConfig) -> SearchExecutor:
        return self._search_factory(
            overrides=config.overrides.to_pipeline_overrides(),
            mode=config.overrides.mode,
        )

    def _resolve_gold(
        self, records: list[QuestionRecord]
    ) -> tuple[list[QuestionRecord], list[str]]:
        return resolve_gold(
            records, account_id=self._account_id, catalog=self._item_catalog
        )

    # -- runs ------------------------------------------------------------

    def run(
        self,
        config: ExperimentConfig,
        records: list[QuestionRecord],
        *,
        known_item_ids: frozenset[str] | None = None,
        chunked_item_ids: frozenset[str] | None = None,
    ) -> RunOutcome:
        resolved, missing = self._resolve_gold(records)
        outcome = run_experiment(
            config,
            resolved,
            search=self._executor(config),
            run_store=self._run_store,
            known_item_ids=known_item_ids,
            chunked_item_ids=chunked_item_ids,
        )
        if missing:
            outcome.warnings = [*_missing_message_warnings(missing), *outcome.warnings]
        return outcome

    def iter_run(
        self,
        config: ExperimentConfig,
        records: list[QuestionRecord],
        *,
        known_item_ids: frozenset[str] | None = None,
        chunked_item_ids: frozenset[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream progress events (ending with ``run.complete``)."""
        resolved, missing = self._resolve_gold(records)
        warnings = _missing_message_warnings(missing)
        for event in iter_experiment(
            config,
            resolved,
            search=self._executor(config),
            run_store=self._run_store,
            known_item_ids=known_item_ids,
            chunked_item_ids=chunked_item_ids,
        ):
            if event.get("event") == "run.complete" and warnings:
                event["warnings"] = [*warnings, *event.get("warnings", [])]
            yield event

    def load_run(self, run_id: str) -> RunSummary:
        return RunSummary(
            run_id=run_id,
            manifest=self._run_store.read_manifest(run_id),
            metrics=self._run_store.read_metrics(run_id),
            question_rows=self._run_store.read_question_rows(run_id),
        )

    def list_runs(self) -> list[str]:
        return self._run_store.list_run_ids()

    def compare(
        self,
        run_a_id: str,
        run_b_id: str,
        *,
        metrics: list[str] | None = None,
        n: int = 10000,
        alpha: float = 0.05,
        seed: int = 0,
    ) -> list[MetricDelta]:
        return compare_runs(
            self.load_run(run_a_id),
            self.load_run(run_b_id),
            metrics=metrics,
            n=n,
            alpha=alpha,
            seed=seed,
        )

    # -- datasets and items ---------------------------------------------

    def validate(
        self,
        records: list[QuestionRecord],
        *,
        known_item_ids: frozenset[str] | None = None,
    ) -> list[ValidationIssue]:
        resolved, missing = self._resolve_gold(records)
        issues = validate_dataset(resolved, known_item_ids=known_item_ids)
        issues.extend(
            ValidationIssue(
                "error",
                "missing_message",
                f"gold message {message_id!r} is not in the corpus",
            )
            for message_id in missing
        )
        return issues

    def list_items(self, import_id: uuid.UUID | None = None) -> list[ItemSummary]:
        return self._item_catalog.list_items(self._account_id, import_id)

    def existing_item_ids(
        self, account_id: uuid.UUID, item_ids: frozenset[str]
    ) -> frozenset[str]:
        return self._item_catalog.existing_item_ids(account_id, item_ids)

    # -- generation ------------------------------------------------------

    def generate(
        self,
        mailbox: str,
        *,
        split: Split = "dev",
        include_trash_spam: bool = False,
    ) -> list[QuestionRecord]:
        if self._passage_source is None or self._llm is None:
            raise RuntimeError(
                "question generation is not available in this deployment"
            )
        passages = self._passage_source.iter_passages(
            mailbox, include_trash_spam=include_trash_spam
        )
        return generate_questions(passages, self._llm, split=split)


def _missing_message_warnings(missing: list[str]) -> list[str]:
    return [
        f"gold message missing from the corpus: {message_id}" for message_id in missing
    ]
