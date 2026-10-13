"""Tests for the runner and run storage."""

from __future__ import annotations

from pathlib import Path

from rosalind_eval.config import ExperimentConfig
from rosalind_eval.corpus import dataset_path, known_item_ids_from_mailbox
from rosalind_eval.dataset import load_dataset
from rosalind_eval.runner import run_experiment
from rosalind_eval.storage import (
    load_manifest,
    load_metrics,
    load_question_rows,
    load_stage_hits,
)
from tests.unit._scripted import ScriptedExecutor, make_run


def _config(name: str) -> ExperimentConfig:
    return ExperimentConfig(name=name, dataset=dataset_path())


def _perfect_executor() -> ScriptedExecutor:
    records = load_dataset(dataset_path())
    runs = {}
    for record in records:
        gold = [item.item_id for item in record.gold]
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


def test_run_writes_all_artifacts(tmp_path: Path) -> None:
    outcome = run_experiment(
        _config("perfect"),
        executor=_perfect_executor(),
        runs_dir=tmp_path,
        known_item_ids=known_item_ids_from_mailbox(),
    )
    root = outcome.paths.root
    for name in (
        "manifest.json",
        "questions.parquet",
        "stage_hits.parquet",
        "metrics.json",
        "events.jsonl",
    ):
        assert (root / name).exists(), name


def test_run_manifest_fields(tmp_path: Path) -> None:
    outcome = run_experiment(
        _config("perfect"), executor=_perfect_executor(), runs_dir=tmp_path
    )
    manifest = load_manifest(outcome.paths.root)
    assert manifest["question_count"] == len(load_dataset(dataset_path()))
    assert len(manifest["dataset_hash"]) == 64
    assert manifest["compute_backend"] in {"cpu", "mps"}
    assert manifest["git_commit"] is None or len(manifest["git_commit"]) >= 7


def test_run_metrics_are_perfect(tmp_path: Path) -> None:
    outcome = run_experiment(
        _config("perfect"), executor=_perfect_executor(), runs_dir=tmp_path
    )
    metrics = load_metrics(outcome.paths.root)
    assert metrics["overall"]["recall_fused"] == 1.0
    assert metrics["overall"]["hit_rate"] == 1.0
    assert metrics["funnel"] == {}
    assert "factual" in metrics["by_type"]
    assert "total_ms" in metrics["latency"]


def test_run_storage_rows(tmp_path: Path) -> None:
    outcome = run_experiment(
        _config("perfect"), executor=_perfect_executor(), runs_dir=tmp_path
    )
    rows = load_question_rows(outcome.paths.root)
    assert len(rows) == len(load_dataset(dataset_path()))
    assert {row["question_id"] for row in rows} == {
        record.id for record in load_dataset(dataset_path())
    }
    assert load_stage_hits(outcome.paths.root)


def test_missing_gold_produces_warnings_and_funnel(tmp_path: Path) -> None:
    records = load_dataset(dataset_path())
    runs = {
        record.id: make_run(
            record,
            lexical=[item.item_id for item in record.gold],
            fused=[item.item_id for item in record.gold],
            reranked=[item.item_id for item in record.gold],
            results=[],
        )
        for record in records
    }
    outcome = run_experiment(
        _config("noknown"),
        executor=ScriptedExecutor(runs),
        runs_dir=tmp_path,
        known_item_ids=frozenset(),
    )
    assert outcome.warnings
    assert all("missing from the index" in w for w in outcome.warnings)
    assert outcome.metrics["funnel"].get("not_in_corpus", 0) > 0


def test_events_have_run_and_question_ids(tmp_path: Path) -> None:
    outcome = run_experiment(
        _config("perfect"), executor=_perfect_executor(), runs_dir=tmp_path
    )
    lines = outcome.paths.events.read_text().splitlines()
    assert any('"run.start"' in line for line in lines)
    assert any('"run.done"' in line for line in lines)
    assert all('"run_id"' in line for line in lines)
