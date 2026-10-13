"""Per-question evaluation result model.

``QuestionRun`` is the executor-independent record of one question's journey
through the search pipeline: every stage's candidates, the assembled results,
versions, timings and flags. Executors (live or scripted) produce it; metrics,
the failure funnel, and run storage all consume it. It is deliberately plain
data so a run can be serialized to Parquet and re-analyzed without the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rosalind_eval.dataset import GoldEvidence

__all__ = ["FinalResult", "QuestionRun", "StageCandidate"]


@dataclass(frozen=True, slots=True)
class StageCandidate:
    """One candidate chunk at one pipeline stage, as an item-level rank."""

    chunk_id: str
    item_id: str
    rank: int
    score: float | None = None


@dataclass(frozen=True, slots=True)
class FinalResult:
    """One assembled result returned by the pipeline."""

    item_id: str
    chunk_id: str
    score: float | None
    matched_in: str  # "body" | "attachment"


@dataclass(frozen=True, slots=True)
class QuestionRun:
    """Everything one question's pipeline run produced."""

    question_id: str
    question_type: str
    split: str
    answerable: bool
    gold: tuple[GoldEvidence, ...]

    plan_fingerprint: str | None = None
    mode_effective: str | None = None
    index_version: str | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None
    reranker_version: str | None = None
    budgets: dict[str, int] = field(default_factory=dict)

    lexical: tuple[StageCandidate, ...] = ()
    semantic: tuple[StageCandidate, ...] = ()
    fused: tuple[StageCandidate, ...] = ()
    reranked: tuple[StageCandidate, ...] = ()
    results: tuple[FinalResult, ...] = ()

    dropped_by_item_cap: int = 0
    lexical_used: bool = False
    semantic_used: bool = False
    rerank_applied: bool = False
    semantic_complete: bool | None = None
    semantic_filter_path: str | None = None
    semantic_scan_limit_hit: bool | None = None
    warnings: tuple[str, ...] = ()
    degraded: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)
    short_circuit: str | None = None

    @property
    def gold_item_ids(self) -> frozenset[str]:
        return frozenset(item.item_id for item in self.gold)
