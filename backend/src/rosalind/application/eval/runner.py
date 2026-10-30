"""Experiment runner: execute every question, compute metrics, write a run.

Executor- and store-agnostic: it takes a ``SearchExecutor`` and an
``EvalRunStore`` port, calls the executor per question, computes per-question
metrics and the failure funnel, aggregates overall/slice metrics and latency,
and writes the run through the store.

``iter_experiment`` yields progress events (and a final ``run.complete`` event
carrying the outcome) so the streaming HTTP endpoint can render progress;
``run_experiment`` drains it and returns the outcome for non-streaming callers.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess  # nosec B404 - fixed argv, no shell, no untrusted input
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from rosalind.application.eval.config import ExperimentConfig
from rosalind.application.eval.dataset import QuestionRecord, dataset_hash
from rosalind.application.eval.funnel import classify_failure
from rosalind.application.eval.metrics import (
    QuestionMetrics,
    aggregate,
    compute_question_metrics,
)
from rosalind.application.eval.models import QuestionRun, RunOutcome
from rosalind.application.eval.ports import EvalRunStore, SearchExecutor
from rosalind.logging import log_context

__all__ = ["iter_experiment", "run_experiment"]


@dataclass(frozen=True, slots=True)
class _Executed:
    record: QuestionRecord
    run: QuestionRun
    metrics: QuestionMetrics
    funnel: str | None


def iter_experiment(
    config: ExperimentConfig,
    records: list[QuestionRecord],
    *,
    search: SearchExecutor,
    run_store: EvalRunStore,
    known_item_ids: frozenset[str] | None = None,
    chunked_item_ids: frozenset[str] | None = None,
    started_at: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """Run an experiment, yielding progress events and a final ``run.complete``."""
    start = started_at or datetime.now(UTC)
    run_id = f"{start.strftime('%Y%m%dT%H%M%SZ')}-{_slug(config.name)}"

    events: list[dict[str, Any]] = [
        {"event": "run.start", "run_id": run_id, "questions": len(records)}
    ]
    yield events[-1]
    executed: list[_Executed] = []

    for record in records:
        events.append(
            {"event": "question.start", "run_id": run_id, "question_id": record.id}
        )
        yield events[-1]
        # Keep the correlation context within a single generator step: it must
        # not span a ``yield`` because the streaming HTTP layer advances sync
        # generators across threadpool contexts.
        with log_context(run_id=run_id, question_id=record.id):
            run = search.execute(record)
            qmetrics = compute_question_metrics(run)
            funnel = classify_failure(
                run,
                known_item_ids=known_item_ids,
                chunked_item_ids=chunked_item_ids,
            )
        executed.append(_Executed(record, run, qmetrics, funnel))
        events.append(
            {
                "event": "question.done",
                "run_id": run_id,
                "question_id": record.id,
                "hit": qmetrics.hit,
                "funnel": funnel,
                "degraded": run.degraded,
            }
        )
        yield events[-1]

    finish = datetime.now(UTC)
    metrics = _aggregate_metrics(executed)
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "name": config.name,
        "config": config.model_dump(mode="json"),
        "dataset_hash": dataset_hash(records),
        "question_count": len(records),
        "git_commit": _git_commit(),
        "compute_backend": _compute_backend(),
        "started_at": start.isoformat(),
        "finished_at": finish.isoformat(),
        "effective_config": _effective_config(executed),
    }
    events.append({"event": "run.done", "run_id": run_id, "questions": len(records)})

    persisted_id = run_store.write(
        manifest=manifest,
        question_rows=[_question_row(item) for item in executed],
        stage_hit_rows=[row for item in executed for row in _stage_rows(item.run)],
        metrics=metrics,
        events=events,
    )
    warnings = _coverage_warnings(records, known_item_ids)
    yield {
        "event": "run.complete",
        "run_id": persisted_id,
        "manifest": manifest,
        "metrics": metrics,
        "warnings": warnings,
        "location": run_store.location(persisted_id),
    }


def run_experiment(
    config: ExperimentConfig,
    records: list[QuestionRecord],
    *,
    search: SearchExecutor,
    run_store: EvalRunStore,
    known_item_ids: frozenset[str] | None = None,
    chunked_item_ids: frozenset[str] | None = None,
    started_at: datetime | None = None,
) -> RunOutcome:
    """Run an experiment to completion and return its outcome."""
    outcome: RunOutcome | None = None
    for event in iter_experiment(
        config,
        records,
        search=search,
        run_store=run_store,
        known_item_ids=known_item_ids,
        chunked_item_ids=chunked_item_ids,
        started_at=started_at,
    ):
        if event["event"] == "run.complete":
            outcome = RunOutcome(
                run_id=event["run_id"],
                manifest=event["manifest"],
                metrics=event["metrics"],
                warnings=event["warnings"],
                location=event["location"],
            )
    if outcome is None:  # pragma: no cover - iter_experiment always completes
        raise RuntimeError("experiment produced no completion event")
    return outcome


def _question_row(item: _Executed) -> dict[str, Any]:
    run = item.run
    metrics = item.metrics
    return {
        "question_id": item.record.id,
        "type": item.record.type,
        "split": item.record.split,
        "answerable": item.record.answerable,
        "plan_fingerprint": run.plan_fingerprint,
        "mode_effective": run.mode_effective,
        "index_version": run.index_version,
        "embedding_model": run.embedding_model,
        "embedding_version": run.embedding_version,
        "reranker_version": run.reranker_version,
        "degraded": run.degraded,
        "rerank_applied": run.rerank_applied,
        "lexical_used": run.lexical_used,
        "semantic_used": run.semantic_used,
        "semantic_complete": run.semantic_complete,
        "semantic_filter_path": run.semantic_filter_path,
        "semantic_scan_limit_hit": run.semantic_scan_limit_hit,
        "dropped_by_item_cap": run.dropped_by_item_cap,
        "recall_lexical": metrics.recall_lexical,
        "recall_semantic": metrics.recall_semantic,
        "recall_fused": metrics.recall_fused,
        "recall_reranked": metrics.recall_reranked,
        "recall_window": metrics.recall_window,
        "mrr": metrics.mrr,
        "ndcg_at_10": metrics.ndcg_at_10,
        "hit": metrics.hit,
        "branch": metrics.branch,
        "funnel": item.funnel,
        "warnings": json.dumps(list(run.warnings)),
        "timings_ms": json.dumps(run.timings_ms),
    }


def _stage_rows(run: QuestionRun) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stage in ("lexical", "semantic", "fused", "reranked"):
        for candidate in getattr(run, stage):
            rows.append(
                {
                    "question_id": run.question_id,
                    "stage": stage,
                    "chunk_id": candidate.chunk_id,
                    "item_id": candidate.item_id,
                    "rank": candidate.rank,
                    "score": candidate.score,
                }
            )
    return rows


def _aggregate_metrics(executed: list[_Executed]) -> dict[str, Any]:
    all_metrics = [item.metrics for item in executed]
    by_type: dict[str, list[QuestionMetrics]] = {}
    by_branch: dict[str, list[QuestionMetrics]] = {}
    funnel_counts: dict[str, int] = {}
    latency: dict[str, list[float]] = {}
    for item in executed:
        by_type.setdefault(item.record.type, []).append(item.metrics)
        by_branch.setdefault(item.metrics.branch, []).append(item.metrics)
        if item.funnel is not None:
            funnel_counts[item.funnel] = funnel_counts.get(item.funnel, 0) + 1
        for name, value in item.run.timings_ms.items():
            latency.setdefault(name, []).append(value)

    return {
        "overall": aggregate(all_metrics),
        "by_type": {key: aggregate(value) for key, value in sorted(by_type.items())},
        "by_branch": {
            key: aggregate(value) for key, value in sorted(by_branch.items())
        },
        "funnel": dict(sorted(funnel_counts.items())),
        "latency": {
            name: {"p50": _percentile(values, 50), "p95": _percentile(values, 95)}
            for name, values in sorted(latency.items())
        },
    }


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round((p / 100) * (len(ordered) - 1)), len(ordered) - 1)
    return ordered[index]


def _effective_config(executed: list[_Executed]) -> dict[str, Any]:
    """The resolved search config from the first question that ran the pipeline.

    Defaults live in ``Settings``; this records what they resolved to (with the
    experiment's overrides applied), so a changed default is visible in the
    manifest rather than only in a ``plan_fingerprint``. Empty when every
    question short-circuited and no plan ran.
    """
    for item in executed:
        run = item.run
        if not run.budgets:
            continue
        return {
            "budgets": dict(run.budgets),
            "fusion": dict(run.fusion),
            "versions": {
                "index_version": run.index_version,
                "embedding_model": run.embedding_model,
                "embedding_version": run.embedding_version,
                "reranker_version": run.reranker_version,
            },
            "mode_effective": run.mode_effective,
        }
    return {}


def _coverage_warnings(
    records: list[QuestionRecord], known_item_ids: frozenset[str] | None
) -> list[str]:
    if known_item_ids is None:
        return []
    missing: set[str] = set()
    for record in records:
        for gold in record.gold:
            if gold.item_id is not None and gold.item_id not in known_item_ids:
                missing.add(gold.item_id)
    return [
        f"gold item missing from the index: {item_id}" for item_id in sorted(missing)
    ]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "run"


def _git_commit() -> str | None:
    try:
        result = subprocess.run(  # nosec B603, B607 - fixed argv, no shell
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _compute_backend() -> str:
    try:
        import torch  # type: ignore[import-not-found]

        if torch.backends.mps.is_available():
            return "mps"
    except Exception as exc:  # noqa: BLE001 - torch is optional
        logging.getLogger(__name__).debug("compute backend detection: %s", exc)
    return "cpu"
