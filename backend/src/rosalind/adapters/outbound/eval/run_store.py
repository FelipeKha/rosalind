"""Parquet-backed run store for eval runs.

A run lives in ``<root>/<run_id>/`` and never touches the production database:

    manifest.json       run id, git commit, config, dataset hash, versions, times
    questions.parquet   one row per question (metrics, funnel, versions, timings)
    stage_hits.parquet  one row per (question, stage, candidate)
    metrics.json        aggregate metrics, slices, funnel counts, latency
    events.jsonl        structured event log with run_id/question_id on every line

Parquet is read back with DuckDB for comparison.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

__all__ = ["ParquetRunStore"]

_QUESTIONS_SCHEMA = pa.schema(
    [
        ("question_id", pa.string()),
        ("type", pa.string()),
        ("split", pa.string()),
        ("answerable", pa.bool_()),
        ("plan_fingerprint", pa.string()),
        ("mode_effective", pa.string()),
        ("index_version", pa.string()),
        ("embedding_model", pa.string()),
        ("embedding_version", pa.string()),
        ("reranker_version", pa.string()),
        ("degraded", pa.bool_()),
        ("rerank_applied", pa.bool_()),
        ("lexical_used", pa.bool_()),
        ("semantic_used", pa.bool_()),
        ("semantic_complete", pa.bool_()),
        ("semantic_filter_path", pa.string()),
        ("semantic_scan_limit_hit", pa.bool_()),
        ("dropped_by_item_cap", pa.int64()),
        ("recall_lexical", pa.float64()),
        ("recall_semantic", pa.float64()),
        ("recall_fused", pa.float64()),
        ("recall_reranked", pa.float64()),
        ("recall_window", pa.float64()),
        ("mrr", pa.float64()),
        ("ndcg_at_10", pa.float64()),
        ("hit", pa.bool_()),
        ("branch", pa.string()),
        ("funnel", pa.string()),
        ("warnings", pa.string()),
        ("timings_ms", pa.string()),
    ]
)

_STAGE_HITS_SCHEMA = pa.schema(
    [
        ("question_id", pa.string()),
        ("stage", pa.string()),
        ("chunk_id", pa.string()),
        ("item_id", pa.string()),
        ("rank", pa.int64()),
        ("score", pa.float64()),
    ]
)


class ParquetRunStore:
    """An ``EvalRunStore`` writing Parquet/JSON under a root directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def write(
        self,
        *,
        manifest: dict[str, Any],
        question_rows: list[dict[str, Any]],
        stage_hit_rows: list[dict[str, Any]],
        metrics: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> str:
        run_id = str(manifest["run_id"])
        run_dir = self._root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str)
        )
        _write_parquet(run_dir / "questions.parquet", _QUESTIONS_SCHEMA, question_rows)
        _write_parquet(
            run_dir / "stage_hits.parquet", _STAGE_HITS_SCHEMA, stage_hit_rows
        )
        (run_dir / "metrics.json").write_text(
            json.dumps(metrics, indent=2, default=str)
        )
        with (run_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, default=str) + "\n")
        return run_id

    def read_manifest(self, run_id: str) -> dict[str, Any]:
        return json.loads((self._root / run_id / "manifest.json").read_text())

    def read_metrics(self, run_id: str) -> dict[str, Any]:
        return json.loads((self._root / run_id / "metrics.json").read_text())

    def read_question_rows(self, run_id: str) -> list[dict[str, Any]]:
        return _read_parquet(self._root / run_id / "questions.parquet")

    def read_stage_hits(self, run_id: str) -> list[dict[str, Any]]:
        return _read_parquet(self._root / run_id / "stage_hits.parquet")

    def list_run_ids(self) -> list[str]:
        if not self._root.exists():
            return []
        return sorted(
            entry.name
            for entry in self._root.iterdir()
            if entry.is_dir() and (entry / "manifest.json").is_file()
        )

    def location(self, run_id: str) -> str:
        return str(self._root / run_id)


def _write_parquet(path: Path, schema: pa.Schema, rows: list[dict[str, Any]]) -> None:
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path)


def _read_parquet(path: Path) -> list[dict[str, Any]]:
    import duckdb

    connection = duckdb.connect()
    try:
        table = connection.execute(
            "SELECT * FROM read_parquet(?)", [str(path)]
        ).to_arrow_table()
    finally:
        connection.close()
    return table.to_pylist()
