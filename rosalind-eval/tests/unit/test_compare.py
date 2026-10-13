"""Tests for run comparison (paired deltas with confidence intervals)."""

from __future__ import annotations

from pathlib import Path

from rosalind_eval.compare import compare_runs, load_run
from rosalind_eval.config import ExperimentConfig
from rosalind_eval.corpus import dataset_path
from rosalind_eval.dataset import load_dataset
from rosalind_eval.runner import run_experiment
from tests.unit._scripted import ScriptedExecutor, make_run


def _run(tmp_path: Path, name: str, *, break_window_for: str | None) -> Path:
    records = load_dataset(dataset_path())
    runs = {}
    for record in records:
        gold = [item.item_id for item in record.gold]
        attachment = any(
            item.evidence and item.evidence.startswith("attachment:")
            for item in record.gold
        )
        results = [] if record.id == break_window_for else gold
        runs[record.id] = make_run(
            record,
            lexical=gold,
            semantic=gold,
            fused=gold,
            reranked=gold,
            results=results,
            matched_in="attachment" if attachment else "body",
        )
    outcome = run_experiment(
        ExperimentConfig(name=name, dataset=dataset_path()),
        executor=ScriptedExecutor(runs),
        runs_dir=tmp_path,
    )
    return outcome.paths.root


def test_compare_reports_deltas_with_ci(tmp_path: Path) -> None:
    run_a = load_run(_run(tmp_path, "a", break_window_for=None))
    run_b = load_run(_run(tmp_path, "b", break_window_for="q_001"))
    deltas = {delta.metric: delta for delta in compare_runs(run_a, run_b, n=500)}

    window = deltas["recall_window"]
    assert window.delta > 0
    assert window.ci_low is not None and window.ci_high is not None
    assert window.p_value is not None and 0.0 <= window.p_value <= 1.0
    assert window.pairs >= 2


def test_compare_identical_runs_have_zero_delta(tmp_path: Path) -> None:
    run_a = load_run(_run(tmp_path, "a", break_window_for=None))
    run_b = load_run(_run(tmp_path, "b", break_window_for=None))
    deltas = {delta.metric: delta for delta in compare_runs(run_a, run_b, n=500)}
    assert deltas["recall_window"].delta == 0.0
