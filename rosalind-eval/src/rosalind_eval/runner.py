"""Experiment runner: execute every question, compute metrics, write a run.

The runner is executor-agnostic: it takes a ``SearchExecutor`` (the live pipeline
or a scripted one for tests), calls it per question, computes per-question
metrics and the failure funnel, aggregates overall/slice metrics and latency,
and writes the run under ``runs/<run_id>/``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess  # nosec B404 - fixed argv, no shell, no untrusted input
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rosalind.logging import log_context

from rosalind_eval.config import ExperimentConfig
from rosalind_eval.dataset import QuestionRecord, load_dataset
from rosalind_eval.executor import SearchExecutor
from rosalind_eval.funnel import classify_failure
from rosalind_eval.metrics import QuestionMetrics, aggregate, compute_question_metrics
from rosalind_eval.results import QuestionRun
from rosalind_eval.storage import RunPaths, write_run

__all__ = ["RunOutcome", "run_experiment"]


@dataclass(slots=True)
class RunOutcome:
    paths: RunPaths
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Executed:
    record: QuestionRecord
    run: QuestionRun
    metrics: QuestionMetrics
    funnel: str | None


def run_experiment(
    config: ExperimentConfig,
    *,
    executor: SearchExecutor,
    runs_dir: Path | None = None,
    known_item_ids: frozenset[str] | None = None,
    chunked_item_ids: frozenset[str] | None = None,
    started_at: datetime | None = None,
) -> RunOutcome:
    """Run an experiment and write its artifacts."""
    records = load_dataset(config.dataset)
    dataset_hash = hashlib.sha256(Path(config.dataset).read_bytes()).hexdigest()

    start = started_at or datetime.now(UTC)
    run_id = f"{start.strftime('%Y%m%dT%H%M%SZ')}-{_slug(config.name)}"
    root = (runs_dir or Path("runs")) / run_id

    events: list[dict[str, Any]] = [
        {"event": "run.start", "run_id": run_id, "questions": len(records)}
    ]
    executed: list[_Executed] = []

    for record in records:
        with log_context(run_id=run_id, question_id=record.id):
            events.append(
                {"event": "question.start", "run_id": run_id, "question_id": record.id}
            )
            run = executor.execute(record)
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

    finish = datetime.now(UTC)
    metrics = _aggregate_metrics(executed)
    manifest = {
        "run_id": run_id,
        "name": config.name,
        "config": config.model_dump(mode="json"),
        "dataset": str(config.dataset),
        "dataset_hash": dataset_hash,
        "question_count": len(records),
        "git_commit": _git_commit(),
        "compute_backend": _compute_backend(),
        "started_at": start.isoformat(),
        "finished_at": finish.isoformat(),
        "versions": _versions(executed),
    }
    events.append({"event": "run.done", "run_id": run_id, "questions": len(records)})

    paths = write_run(
        root,
        manifest=manifest,
        question_rows=[_question_row(item) for item in executed],
        stage_hit_rows=[row for item in executed for row in _stage_rows(item.run)],
        metrics=metrics,
        events=events,
    )
    warnings = _coverage_warnings(records, known_item_ids)
    return RunOutcome(
        paths=paths, manifest=manifest, metrics=metrics, warnings=warnings
    )


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


def _versions(executed: list[_Executed]) -> dict[str, Any]:
    for item in executed:
        run = item.run
        if run.index_version or run.embedding_model or run.reranker_version:
            return {
                "index_version": run.index_version,
                "embedding_model": run.embedding_model,
                "embedding_version": run.embedding_version,
                "reranker_version": run.reranker_version,
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
            if gold.item_id not in known_item_ids:
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
