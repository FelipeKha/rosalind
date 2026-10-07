"""Fusion of lexical and semantic retrieval results (online search pipeline, step 3).

Layer: ``application``. A pure function with no SQLAlchemy, pg_search, pgvector,
or database access. It merges the two ranked chunk lists by ``chunk_id``, scores
them with reciprocal rank fusion, sorts deterministically, applies the
per-message chunk cap, and truncates to ``fused_k``. Its job is to get the
relevant chunks into the reranker window, not to produce the final order.

Every candidate preserves its per-branch rank and score, so later assembly can
tell whether a result matched by keyword, by meaning, or both, and the
evaluation harness can see which branch found the answer. RRF uses ranks, not
BM25/cosine scores, so no normalization is needed; the raw branch scores are
kept purely as metadata. When one branch is missing (lexical-only mode, or a
degraded call), fusion passes the other list through unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from rosalind.application.search.plan import FusionStrategy, SearchPlan
from rosalind.application.search.retrieve import LexicalResult
from rosalind.application.search.semantic import SemanticResult

__all__ = ["FusedCandidate", "FusedCandidates", "fuse"]


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    """One merged chunk, ready for the reranker (or assembly when reranking is off)."""

    chunk_id: uuid.UUID
    email_id: uuid.UUID

    fused_score: float
    fused_rank: int  # 1-based, final position after capping and truncation

    lexical_rank: int | None
    lexical_score: float | None

    semantic_rank: int | None
    semantic_distance: float | None

    def __post_init__(self) -> None:
        if self.fused_rank < 1:
            raise ValueError("fused_rank must be at least 1")
        if self.lexical_rank is None and self.semantic_rank is None:
            raise ValueError("a fused candidate must come from at least one branch")


@dataclass(frozen=True, slots=True)
class FusedCandidates:
    """What step 3 returns: up to ``fused_k`` candidates in deterministic order."""

    candidates: tuple[FusedCandidate, ...]
    lexical_used: bool
    semantic_used: bool
    dropped_by_item_cap: int


@dataclass(frozen=True, slots=True)
class _Merged:
    """A chunk seen in at least one branch, before RRF scoring."""

    chunk_id: uuid.UUID
    email_id: uuid.UUID
    lexical_rank: int | None
    lexical_score: float | None
    semantic_rank: int | None
    semantic_distance: float | None


@dataclass(frozen=True, slots=True)
class _Scored:
    """A merged candidate with its fused RRF score."""

    chunk_id: uuid.UUID
    email_id: uuid.UUID
    fused_score: float
    lexical_rank: int | None
    lexical_score: float | None
    semantic_rank: int | None
    semantic_distance: float | None


def fuse(
    plan: SearchPlan,
    lexical: LexicalResult | None,
    semantic: SemanticResult | None,
) -> FusedCandidates:
    """Merge, score, sort, cap per message, and truncate to ``fused_k``.

    The order of operations is deliberate: the per-message cap runs *after*
    scoring and sorting but *before* truncation, so a long email cannot consume
    the whole ``fused_k`` budget before diversity is imposed.
    """
    if lexical is None and semantic is None:
        raise ValueError("at least one retrieval branch is required")

    config = plan.fusion
    if config.strategy is not FusionStrategy.RRF:
        raise NotImplementedError(
            f"fusion strategy {config.strategy.value!r} is not implemented"
        )

    merged = _merge(lexical, semantic)
    scored = _score(merged, config.rrf_k, config.lexical_weight, config.semantic_weight)
    ordered = sorted(scored, key=_sort_key)

    kept, dropped = _cap(ordered, config.max_chunks_per_item)
    kept = kept[: plan.budgets.fused_k]

    candidates = tuple(
        FusedCandidate(
            chunk_id=candidate.chunk_id,
            email_id=candidate.email_id,
            fused_score=candidate.fused_score,
            fused_rank=rank,
            lexical_rank=candidate.lexical_rank,
            lexical_score=candidate.lexical_score,
            semantic_rank=candidate.semantic_rank,
            semantic_distance=candidate.semantic_distance,
        )
        for rank, candidate in enumerate(kept, start=1)
    )

    return FusedCandidates(
        candidates=candidates,
        lexical_used=lexical is not None,
        semantic_used=semantic is not None,
        dropped_by_item_cap=dropped,
    )


def _merge(
    lexical: LexicalResult | None,
    semantic: SemanticResult | None,
) -> dict[uuid.UUID, _Merged]:
    merged: dict[uuid.UUID, _Merged] = {}

    if lexical is not None:
        for lexical_hit in lexical.hits:
            merged[lexical_hit.chunk_id] = _Merged(
                chunk_id=lexical_hit.chunk_id,
                email_id=lexical_hit.email_id,
                lexical_rank=lexical_hit.rank,
                lexical_score=lexical_hit.score,
                semantic_rank=None,
                semantic_distance=None,
            )

    if semantic is not None:
        for semantic_hit in semantic.hits:
            existing = merged.get(semantic_hit.chunk_id)
            if existing is None:
                merged[semantic_hit.chunk_id] = _Merged(
                    chunk_id=semantic_hit.chunk_id,
                    email_id=semantic_hit.email_id,
                    lexical_rank=None,
                    lexical_score=None,
                    semantic_rank=semantic_hit.rank,
                    semantic_distance=semantic_hit.distance,
                )
                continue
            if existing.email_id != semantic_hit.email_id:
                raise ValueError(
                    f"chunk {semantic_hit.chunk_id} has inconsistent email_id across branches"
                )
            merged[semantic_hit.chunk_id] = _Merged(
                chunk_id=existing.chunk_id,
                email_id=existing.email_id,
                lexical_rank=existing.lexical_rank,
                lexical_score=existing.lexical_score,
                semantic_rank=semantic_hit.rank,
                semantic_distance=semantic_hit.distance,
            )

    return merged


def _score(
    merged: dict[uuid.UUID, _Merged],
    rrf_k: int,
    lexical_weight: float,
    semantic_weight: float,
) -> list[_Scored]:
    scored: list[_Scored] = []
    for candidate in merged.values():
        score = 0.0
        if candidate.lexical_rank is not None:
            score += lexical_weight / (rrf_k + candidate.lexical_rank)
        if candidate.semantic_rank is not None:
            score += semantic_weight / (rrf_k + candidate.semantic_rank)
        scored.append(
            _Scored(
                chunk_id=candidate.chunk_id,
                email_id=candidate.email_id,
                fused_score=score,
                lexical_rank=candidate.lexical_rank,
                lexical_score=candidate.lexical_score,
                semantic_rank=candidate.semantic_rank,
                semantic_distance=candidate.semantic_distance,
            )
        )
    return scored


def _branch_count(candidate: _Scored) -> int:
    return int(candidate.lexical_rank is not None) + int(
        candidate.semantic_rank is not None
    )


def _best_rank(candidate: _Scored) -> int:
    ranks = [
        rank
        for rank in (candidate.lexical_rank, candidate.semantic_rank)
        if rank is not None
    ]
    return min(ranks)


def _sort_key(candidate: _Scored) -> tuple[float, int, int, uuid.UUID]:
    return (
        -candidate.fused_score,
        -_branch_count(candidate),
        _best_rank(candidate),
        candidate.chunk_id,
    )


def _cap(
    ordered: list[_Scored],
    max_chunks_per_item: int,
) -> tuple[list[_Scored], int]:
    kept: list[_Scored] = []
    seen: dict[uuid.UUID, int] = {}
    dropped = 0
    for candidate in ordered:
        count = seen.get(candidate.email_id, 0)
        if count >= max_chunks_per_item:
            dropped += 1
            continue
        seen[candidate.email_id] = count + 1
        kept.append(candidate)
    return kept, dropped
