"""Tests for the eval CLI surface."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rosalind_eval.cli import app
from rosalind_eval.corpus import dataset_path, mailbox_path

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "compare", "validate-dataset", "generate-questions"):
        assert command in result.output


def test_run_requires_database_and_account(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("name: baseline\ndataset: data.jsonl\n")
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == 2


def test_run_rejects_an_invalid_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("name: x\ndataset: d.jsonl\nbogus: 1\n")
    result = runner.invoke(app, ["run", "--config", str(path)])
    assert result.exit_code == 2


def test_validate_fixture_dataset_passes() -> None:
    result = runner.invoke(
        app,
        [
            "validate-dataset",
            str(dataset_path()),
            "--mailbox",
            str(mailbox_path()),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ok" in result.output


def test_validate_dataset_rejects_invalid_record(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    path.write_text(json.dumps({"id": "q1", "type": "factual"}) + "\n")
    result = runner.invoke(app, ["validate-dataset", str(path)])
    assert result.exit_code == 2


def test_validate_dataset_known_item_ids_file(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "q1",
                "type": "factual",
                "query": "q",
                "gold": [{"item_id": "e_1"}],
            }
        )
        + "\n"
    )
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps(["e_1"]))
    result = runner.invoke(
        app, ["validate-dataset", str(dataset), "--known-item-ids", str(ids)]
    )
    assert result.exit_code == 0, result.output


def test_validate_dataset_missing_item_is_an_error(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "q1",
                "type": "factual",
                "query": "q",
                "gold": [{"item_id": "e_missing"}],
            }
        )
        + "\n"
    )
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps(["e_1"]))
    result = runner.invoke(
        app, ["validate-dataset", str(dataset), "--known-item-ids", str(ids)]
    )
    assert result.exit_code == 2
