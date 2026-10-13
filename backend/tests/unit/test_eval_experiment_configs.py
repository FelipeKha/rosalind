"""Every eval experiment YAML loads and maps onto the expected override."""

from __future__ import annotations

from pathlib import Path

from rosalind.application.eval.config import load_config
from rosalind.application.search import FusionStrategy
from rosalind.application.search.rerank import RerankTextMode

CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "eval" / "experiments"


def _load(name: str):
    return load_config(CONFIGS / name)


def test_all_experiment_configs_load() -> None:
    files = sorted(CONFIGS.glob("*.yaml"))
    assert files, "expected experiment configs"
    for path in files:
        config = load_config(path)
        config.overrides.to_pipeline_overrides()


def test_mode_configs() -> None:
    assert _load("mode-lexical.yaml").overrides.mode == "lexical"
    assert _load("mode-semantic.yaml").overrides.mode == "semantic"
    assert _load("mode-hybrid.yaml").overrides.mode == "hybrid"


def test_fusion_rrf_default() -> None:
    overrides = _load("fusion-rrf-k60.yaml").overrides.to_pipeline_overrides()
    assert overrides.fusion is not None
    assert overrides.fusion.strategy is FusionStrategy.RRF
    assert overrides.fusion.rrf_k == 60


def test_fusion_convex_sets_alpha() -> None:
    overrides = _load("fusion-convex-a0.5.yaml").overrides.to_pipeline_overrides()
    assert overrides.fusion is not None
    assert overrides.fusion.strategy is FusionStrategy.CONVEX
    assert overrides.fusion.convex_alpha == 0.5


def test_rerank_configs() -> None:
    assert _load("rerank-off.yaml").overrides.to_pipeline_overrides().disable_reranker
    assert _load("rerank-k20.yaml").overrides.to_pipeline_overrides().rerank_k == 20
    assert _load("rerank-k40.yaml").overrides.to_pipeline_overrides().rerank_k == 40


def test_rerank_display_text_sets_text_mode() -> None:
    config = _load("rerank-display-text.yaml")
    assert config.overrides.to_rerank_text_mode() is RerankTextMode.DISPLAY
    assert (
        config.overrides.to_pipeline_overrides().rerank_text_mode
        is RerankTextMode.DISPLAY
    )


def test_cap_configs() -> None:
    for name, cap in (("cap-1.yaml", 1), ("cap-2.yaml", 2), ("cap-none.yaml", 1000)):
        fusion = _load(name).overrides.to_pipeline_overrides().fusion
        assert fusion is not None
        assert fusion.max_chunks_per_item == cap
