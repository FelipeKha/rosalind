"""Per-question evaluation result model and other eval value objects.

``QuestionRun`` is the executor-independent record of one question's journey
through the search pipeline: every stage's candidates, the assembled results,
versions, timings and flags. Executors (live or scripted) produce it; metrics,
the failure funnel, and run storage all consume it.

Plain dataclasses; no framework, SQL, or provider imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rosalind.application.eval.dataset import GoldEvidence, QuestionType

__all__ = [
    "DraftQuestion",
    "FinalResult",
    "ItemSummary",
    "Passage",
    "QuestionRun",
    "RunOutcome",
    "StageCandidate",
]


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
        """Resolved canonical gold ids; unresolved entries are excluded."""
        return frozenset(item.item_id for item in self.gold if item.item_id is not None)


@dataclass(frozen=True, slots=True)
class Passage:
    """One mailbox message reduced to what question generation needs."""

    item_id: str
    message_id: str
    subject: str | None
    text: str
    attachment_sha256: str | None


@dataclass(frozen=True, slots=True)
class ItemSummary:
    """A keyable corpus item, for manual gold authoring."""

    item_id: str
    subject: str | None
    sender: str | None
    occurred_at: datetime | None
    has_attachments: bool
    is_trash_or_spam: bool


@dataclass(slots=True)
class RunOutcome:
    """The result of an experiment run."""

    run_id: str
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    location: str | None = None


class DraftQuestion(BaseModel):
    """Structured output the LLM must return for one passage."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    type: QuestionType
    answer: str = Field(min_length=1)
    keywords: str | None = None
