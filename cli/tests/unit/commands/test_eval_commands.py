"""Tests for the `rosalind eval ...` CLI surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from cli.app import app
from cli.commands import eval as eval_command

runner = CliRunner()


def test_eval_help_lists_commands() -> None:
    result = runner.invoke(app, ["eval", "--help"])
    assert result.exit_code == 0
    for command in (
        "run",
        "runs",
        "compare",
        "validate-dataset",
        "generate-questions",
        "items",
    ):
        assert command in result.output


def test_resolve_dataset_relative_to_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("name: x\ndataset: data.jsonl\n")
    dataset = tmp_path / "data.jsonl"
    dataset.write_text("{}\n")
    resolved = eval_command._resolve_dataset(config, {"dataset": "data.jsonl"})
    assert resolved == dataset


def test_read_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    path.write_text(json.dumps({"id": "q1"}) + "\n")
    assert eval_command._read_jsonl(path) == [{"id": "q1"}]


def test_read_jsonl_rejects_bad_line(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    path.write_text("{not json\n")
    with pytest.raises(typer.Exit):
        eval_command._read_jsonl(path)
