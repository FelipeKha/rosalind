"""Experiment configuration for rosalind-eval.

An experiment is a YAML file naming a dataset, a set of pipeline overrides, and
a run name. Overrides map onto the app's internal ``PipelineOverrides`` (never
onto MCP/REST tool parameters), so an experiment can perturb budgets, fusion, or
the reranker without changing the external surface.

YAML shape (all override fields optional)::

    name: rerank-off
    dataset: ../e2e/gold/email_rag_cases.yaml
    description: baseline without the cross-encoder
    overrides:
      mode: hybrid            # hybrid | lexical | semantic
      lexical_k: 50
      semantic_k: 50
      fused_k: 40
      rerank_k: 40
      window_k: 25
      reranker: bge-reranker-v2-m3/v1
      disable_reranker: false
      chunk_prefix: true      # rerank text: contextual prefix vs display text
      fusion:
        strategy: rrf         # rrf | convex
        rrf_k: 60
        lexical_weight: 1.0
        semantic_weight: 1.0
        convex_alpha: null
        max_chunks_per_item: 2
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rosalind.application.search import FusionConfig, FusionStrategy
from rosalind.application.search.overrides import PipelineOverrides
from rosalind.application.search.rerank import RerankTextMode

__all__ = [
    "ExperimentConfig",
    "FusionSettings",
    "OverridesSettings",
    "load_config",
]

SearchModeName = Literal["hybrid", "lexical", "semantic"]


class FusionSettings(BaseModel):
    """Fusion strategy and parameters. Mirrors the app's ``FusionConfig``."""

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["rrf", "convex"] = "rrf"
    rrf_k: int = Field(60, ge=1)
    lexical_weight: float = Field(1.0, ge=0.0)
    semantic_weight: float = Field(1.0, ge=0.0)
    convex_alpha: float | None = Field(None, ge=0.0, le=1.0)
    max_chunks_per_item: int = Field(2, ge=1)

    def to_fusion_config(self) -> FusionConfig:
        """Build the app's ``FusionConfig``, surfacing any invariant violation."""
        return FusionConfig(
            strategy=FusionStrategy(self.strategy),
            rrf_k=self.rrf_k,
            lexical_weight=self.lexical_weight,
            semantic_weight=self.semantic_weight,
            convex_alpha=self.convex_alpha,
            max_chunks_per_item=self.max_chunks_per_item,
        )


class OverridesSettings(BaseModel):
    """Per-experiment pipeline overrides. Internal API only."""

    model_config = ConfigDict(extra="forbid")

    mode: SearchModeName | None = None
    lexical_k: int | None = Field(None, ge=1)
    semantic_k: int | None = Field(None, ge=1)
    fused_k: int | None = Field(None, ge=1)
    rerank_k: int | None = Field(None, ge=1)
    window_k: int | None = Field(None, ge=1)
    reranker: str | None = None
    disable_reranker: bool = False
    chunk_prefix: bool | None = None
    fusion: FusionSettings | None = None

    def to_pipeline_overrides(self) -> PipelineOverrides:
        """Map onto the app's internal ``PipelineOverrides`` (mode excluded)."""
        return PipelineOverrides(
            reranker=self.reranker,
            disable_reranker=self.disable_reranker,
            lexical_k=self.lexical_k,
            semantic_k=self.semantic_k,
            fused_k=self.fused_k,
            rerank_k=self.rerank_k,
            window_k=self.window_k,
            fusion=self.fusion.to_fusion_config() if self.fusion else None,
        )

    def to_rerank_text_mode(self) -> RerankTextMode | None:
        """The rerank passage text mode, or ``None`` when unset."""
        if self.chunk_prefix is None:
            return None
        return RerankTextMode.INDEX if self.chunk_prefix else RerankTextMode.DISPLAY


class ExperimentConfig(BaseModel):
    """A validated experiment definition loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    dataset: Path
    description: str | None = None
    overrides: OverridesSettings = OverridesSettings()

    @model_validator(mode="after")
    def _validate_overrides(self) -> ExperimentConfig:
        # Building the derived app objects surfaces cross-field invariant
        # violations (convex needs alpha, reranker/disable conflict, budget
        # ordering) at load time rather than mid-run.
        self.overrides.to_pipeline_overrides()
        return self


def load_config(path: str | Path) -> ExperimentConfig:
    """Load and validate an experiment config from a YAML file."""
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text())
    except FileNotFoundError as exc:
        raise ValueError(f"config file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {config_path}: {exc}") from exc
    if raw is None:
        raise ValueError(f"config file is empty: {config_path}")
    if not isinstance(raw, dict):
        raise TypeError(f"config must be a mapping, got {type(raw).__name__}")
    return ExperimentConfig.model_validate(raw)
