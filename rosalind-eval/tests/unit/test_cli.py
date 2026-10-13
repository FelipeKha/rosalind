"""Tests for the eval CLI surface (Phase 2 scaffold)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from rosalind_eval.cli import app

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "compare", "validate-dataset"):
        assert command in result.output


def test_run_validates_a_minimal_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("name: baseline\ndataset: data.jsonl\n")
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == 0
    assert "baseline" in result.output


def test_run_rejects_an_invalid_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("name: x\ndataset: d.jsonl\nbogus: 1\n")
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == 2


def test_validate_dataset_counts_records(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    path.write_text('{"id": "q1"}\n{"id": "q2"}\n')
    result = runner.invoke(app, ["validate-dataset", str(path)])
    assert result.exit_code == 0
    assert "2" in result.output


def test_validate_dataset_rejects_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    path.write_text("{not json\n")
    result = runner.invoke(app, ["validate-dataset", str(path)])
    assert result.exit_code == 2
