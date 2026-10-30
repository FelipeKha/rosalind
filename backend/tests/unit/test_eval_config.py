"""Tests for the eval experiment-config loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rosalind.application.eval.config import load_config

CONFIGS = (
    Path(__file__).resolve().parents[3] / "eval" / "email-rag-synthetic" / "experiments"
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body)
    return path


def test_loads_minimal_config(tmp_path: Path) -> None:
    path = _write(tmp_path, "name: baseline\ndataset: data.jsonl\n")
    config = load_config(path)
    assert config.name == "baseline"
    assert config.dataset == Path("data.jsonl")
    overrides = config.overrides.to_pipeline_overrides()
    assert overrides.lexical_k is None
    assert overrides.fusion is None


def test_loads_config_with_overrides(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
name: rerank-on
dataset: data.jsonl
overrides:
  mode: hybrid
  rerank_k: 40
  chunk_prefix: false
  fusion:
    strategy: rrf
    rrf_k: 20
""",
    )
    config = load_config(path)
    overrides = config.overrides.to_pipeline_overrides()
    assert overrides.rerank_k == 40
    assert overrides.fusion is not None
    assert overrides.fusion.rrf_k == 20
    assert config.overrides.to_rerank_text_mode() is not None


def test_rejects_unknown_field(tmp_path: Path) -> None:
    path = _write(tmp_path, "name: x\ndataset: d.jsonl\nbogus: 1\n")
    with pytest.raises(ValidationError):
        load_config(path)


def test_missing_name_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "dataset: d.jsonl\n")
    with pytest.raises(ValidationError):
        load_config(path)


def test_convex_without_alpha_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
name: convex
dataset: d.jsonl
overrides:
  fusion:
    strategy: convex
""",
    )
    with pytest.raises(ValidationError):
        load_config(path)


def test_reranker_and_disable_conflict_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
name: conflict
dataset: d.jsonl
overrides:
  reranker: bge-reranker-v2-m3/v1
  disable_reranker: true
""",
    )
    with pytest.raises(ValidationError):
        load_config(path)


def test_empty_config_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "\n")
    with pytest.raises(ValueError):
        load_config(path)


def test_non_mapping_config_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(TypeError):
        load_config(path)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_repo_minimal_config_loads() -> None:
    config = load_config(CONFIGS / "baseline.yaml")
    assert config.name == "baseline"


def test_repo_hybrid_config_loads() -> None:
    config = load_config(CONFIGS / "rrf-rerank40.yaml")
    assert config.name == "rrf-rerank40"
    assert config.overrides.to_pipeline_overrides().rerank_k == 40
