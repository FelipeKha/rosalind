"""Tests for the eval runner and run storage."""

from __future__ import annotations

from pathlib import Path

from rosalind.adapters.outbound.eval.run_store import ParquetRunStore
from rosalind.application.eval.config import ExperimentConfig
from rosalind.application.eval.dataset import load_dataset
from rosalind.application.eval.runner import run_experiment
from tests.eval_support import (
    ScriptedExecutor,
    dataset_path,
    gold_ids,
    known_item_ids,
    make_run,
    resolve_fixture_records,
)


def _config(name: str) -> ExperimentConfig:
    return ExperimentConfig(name=name, dataset=dataset_path())


def _perfect_executor() -> ScriptedExecutor:
    records = resolve_fixture_records()
    runs = {}
    for record in records:
        gold = gold_ids(record)
        attachment = any(
            item.evidence and item.evidence.startswith("attachment:")
            for item in record.gold
        )
        runs[record.id] = make_run(
            record,
            lexical=gold,
            semantic=gold,
            fused=gold,
            reranked=gold,
            results=gold,
            matched_in="attachment" if attachment else "body",
        )
    return ScriptedExecutor(runs)


def _run(tmp_path: Path, name: str = "perfect"):
    store = ParquetRunStore(tmp_path)
    records = resolve_fixture_records()
    outcome = run_experiment(
        _config(name),
        records,
        search=_perfect_executor(),
        run_store=store,
        known_item_ids=known_item_ids(),
    )
    return outcome, store


def test_run_writes_all_artifacts(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path)
    root = Path(outcome.location or "")
    for name in (
        "manifest.json",
        "questions.parquet",
        "stage_hits.parquet",
        "metrics.json",
        "events.jsonl",
    ):
        assert (root / name).exists(), name


def test_run_manifest_fields(tmp_path: Path) -> None:
    outcome, store = _run(tmp_path)
    manifest = store.read_manifest(outcome.run_id)
    assert manifest["question_count"] == len(load_dataset(dataset_path()))
    assert len(manifest["dataset_hash"]) == 64
    assert manifest["compute_backend"] in {"cpu", "mps"}
    assert manifest["git_commit"] is None or len(manifest["git_commit"]) >= 7


def test_run_metrics_are_perfect(tmp_path: Path) -> None:
    outcome, store = _run(tmp_path)
    metrics = store.read_metrics(outcome.run_id)
    assert metrics["overall"]["recall_fused"] == 1.0
    assert metrics["overall"]["hit_rate"] == 1.0
    assert metrics["funnel"] == {}
    assert "factual" in metrics["by_type"]
    assert "total_ms" in metrics["latency"]


def test_run_storage_rows(tmp_path: Path) -> None:
    outcome, store = _run(tmp_path)
    rows = store.read_question_rows(outcome.run_id)
    assert len(rows) == len(load_dataset(dataset_path()))
    assert store.read_stage_hits(outcome.run_id)


def test_missing_gold_produces_warnings_and_funnel(tmp_path: Path) -> None:
    store = ParquetRunStore(tmp_path)
    records = resolve_fixture_records()
    runs = {
        record.id: make_run(
            record,
            lexical=gold_ids(record),
            fused=gold_ids(record),
            reranked=gold_ids(record),
            results=[],
        )
        for record in records
    }
    outcome = run_experiment(
        _config("noknown"),
        records,
        search=ScriptedExecutor(runs),
        run_store=store,
        known_item_ids=frozenset(),
    )
    assert outcome.warnings
    assert all("missing from the index" in w for w in outcome.warnings)
    assert outcome.metrics["funnel"].get("not_in_corpus", 0) > 0


def test_events_have_run_and_question_ids(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path)
    events_path = Path(outcome.location or "") / "events.jsonl"
    lines = events_path.read_text().splitlines()
    assert any('"run.start"' in line for line in lines)
    assert any('"run.done"' in line for line in lines)
    assert all('"run_id"' in line for line in lines)
