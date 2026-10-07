"""Reranking of fused search candidates (online search pipeline, step 4).

Layer: ``application``. The contracts are plain frozen dataclasses; the
``rerank`` function orchestrates text fetch, truncation, and scoring behind the
``RerankerPort`` / ``ChunkTextPort`` protocols, so no HTTP or SQL concepts leak
in. The concrete adapters live in ``adapters.outbound.search``.

A cross-encoder scores each fused candidate against the query in one batched
call; the reranker only reorders the candidates fusion already admitted. It
never retrieves new chunks, removes candidates by threshold, or merges them.

Failure policy is all-or-nothing: if the reranker is unavailable (a transient
backend failure or the overall deadline) the result is ``applied=False`` with
the fused order preserved and a ``RERANK_SKIPPED`` warning — never a mixture of
reranked and non-reranked candidates. Raw model scores are kept (higher is
better); ordering ties break deterministically on ``fused_rank`` then
``chunk_id``.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from rosalind.application.search.fusion import FusedCandidates
from rosalind.application.search.plan import PlanWarning, SearchPlan, WarningCode
from rosalind.domain.search import TokenCounter, truncate_to_tokens

if TYPE_CHECKING:
    from rosalind.application.search.ports import (
        ChunkTextPort,
        RerankConfig,
        RerankerPort,
    )

__all__ = [
    "ChunkText",
    "RerankBackendError",
    "RerankError",
    "RerankInput",
    "RerankResult",
    "RerankStats",
    "RerankTextMode",
    "RerankedHit",
    "rerank",
]

_CROSS_ENCODER_SPECIAL_TOKENS = 3
"""Extra tokens the cross-encoder inserts around a query/passage pair
(``[CLS]`` plus two ``[SEP]``). The injected ``TokenCounter`` counts text
without special tokens, so this fixed allowance is subtracted from the input
budget before deciding how much passage remains."""


class RerankTextMode(StrEnum):
    INDEX = "index"  # text_for_index (contextual prefix) — v1 default
    DISPLAY = "display"  # text_for_display


class RerankError(Exception):
    """Reranking could not produce a valid result (invalid input/response/config)."""


class RerankBackendError(RerankError):
    """A transient reranker failure (timeout, 429, 5xx) that outlived retries."""


@dataclass(frozen=True, slots=True)
class ChunkText:
    """One candidate's text fetched for scoring."""

    chunk_id: uuid.UUID
    text: str


@dataclass(frozen=True, slots=True)
class RerankInput:
    """The unit passed between fetch → truncate → score."""

    chunk_id: uuid.UUID
    fused_rank: int
    text: str


@dataclass(frozen=True, slots=True)
class RerankedHit:
    """One candidate in its final position.

    ``fused_score`` is carried alongside ``rerank_score`` so assembly can report
    a meaningful ranking score in both paths without keeping a separate lookup
    into ``FusedCandidates``.
    """

    chunk_id: uuid.UUID
    rerank_rank: int
    rerank_score: float | None  # None when reranking was not applied
    fused_rank: int
    fused_score: float

    def __post_init__(self) -> None:
        if self.rerank_rank < 1:
            raise ValueError("rerank_rank must be at least 1")
        if self.fused_rank < 1:
            raise ValueError("fused_rank must be at least 1")


@dataclass(frozen=True, slots=True)
class RerankStats:
    """Observability for one rerank step. Not agent-facing: passage truncation
    is a chunking/window concern the agent cannot act on, so it lives here and
    in logs, not in ``warnings``."""

    candidates_in: int
    scored: int
    dropped_missing: int  # chunk id vanished between retrieve and rerank
    truncated_passages: int  # truncated to fit the input budget
    batches: int  # estimated batch requests: ceil(scored / max_batch_size)
    fetch_ms: float
    score_ms: float


@dataclass(frozen=True, slots=True)
class RerankResult:
    """What step 4 returns: a final order, plus whether it came from the model."""

    ranked: tuple[RerankedHit, ...]
    applied: bool
    model: str | None
    warnings: tuple[PlanWarning, ...]
    stats: RerankStats
    elapsed_ms: float


async def rerank(
    plan: SearchPlan,
    fused: FusedCandidates,
    *,
    texts: ChunkTextPort,
    reranker: RerankerPort | None = None,
    token_counter: TokenCounter | None = None,
    config: RerankConfig | None = None,
) -> RerankResult:
    """Rerank the top ``rerank_k`` fused candidates, or fall back to fused order.

    The reranker scores the candidates fusion already admitted; it never widens
    the candidate set. When reranking is disabled, skipped, or fails, ``applied``
    is ``False`` and ``ranked`` carries the fused order (limited to ``window_k``)
    with ``rerank_score=None``, so assembly never has to branch.

    ``reranker`` / ``token_counter`` / ``config`` are optional only so a caller
    with reranking disabled can short-circuit without wiring them; when
    reranking is enabled they must all be present.
    """
    started = time.perf_counter()

    def not_applied(
        warnings: tuple[PlanWarning, ...],
        *,
        fetch_ms: float,
        score_ms: float,
        candidates_in: int,
        dropped_missing: int = 0,
        truncated_passages: int = 0,
    ) -> RerankResult:
        return RerankResult(
            ranked=_fused_order(plan, fused),
            applied=False,
            model=plan.versions.reranker,
            warnings=warnings,
            stats=RerankStats(
                candidates_in=candidates_in,
                scored=0,
                dropped_missing=dropped_missing,
                truncated_passages=truncated_passages,
                batches=0,
                fetch_ms=fetch_ms,
                score_ms=score_ms,
            ),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    if not fused.candidates or not plan.rerank_enabled:
        return not_applied((), fetch_ms=0.0, score_ms=0.0, candidates_in=0)

    if reranker is None or token_counter is None or config is None:
        raise RerankError(
            "reranking is enabled but no reranker/tokenizer/config is wired"
        )

    query = plan.rerank_query
    if query is None:
        raise RerankError("ranked plan has no query text for reranking")

    top = fused.candidates[: plan.budgets.rerank_k]
    chunk_ids = tuple(candidate.chunk_id for candidate in top)

    fetch_started = time.perf_counter()
    fetched = await texts.get_rerank_texts(chunk_ids, config.text_mode)
    fetch_ms = (time.perf_counter() - fetch_started) * 1000

    by_id = {item.chunk_id: item.text for item in fetched}
    inputs: list[RerankInput] = []
    dropped_missing = 0
    for candidate in top:
        text = by_id.get(candidate.chunk_id)
        if text is None:
            dropped_missing += 1
            continue
        inputs.append(
            RerankInput(
                chunk_id=candidate.chunk_id,
                fused_rank=candidate.fused_rank,
                text=text,
            )
        )

    if not inputs:
        return not_applied(
            (),
            fetch_ms=fetch_ms,
            score_ms=0.0,
            candidates_in=len(top),
            dropped_missing=dropped_missing,
        )

    query_tokens = token_counter.count(query)
    passage_budget = (
        config.max_input_tokens - query_tokens - _CROSS_ENCODER_SPECIAL_TOKENS
    )
    if passage_budget <= 0:
        raise RerankError(
            f"query uses {query_tokens} tokens, leaving no passage budget "
            f"(max_input_tokens={config.max_input_tokens})"
        )

    passages: list[str] = []
    truncated_passages = 0
    for item in inputs:
        text, was_truncated = truncate_to_tokens(
            item.text, passage_budget, token_counter
        )
        if was_truncated:
            truncated_passages += 1
        passages.append(text)

    score_started = time.perf_counter()
    try:
        async with asyncio.timeout(config.deadline_ms / 1000):
            scores = await reranker.rerank(query, tuple(passages))
    except RerankBackendError, TimeoutError:
        return not_applied(
            (
                PlanWarning(
                    code=WarningCode.RERANK_SKIPPED,
                    message="reranking unavailable; returning fused order",
                ),
            ),
            fetch_ms=fetch_ms,
            score_ms=(time.perf_counter() - score_started) * 1000,
            candidates_in=len(top),
            dropped_missing=dropped_missing,
            truncated_passages=truncated_passages,
        )
    score_ms = (time.perf_counter() - score_started) * 1000

    if len(scores) != len(inputs):
        raise RerankError(
            f"reranker returned {len(scores)} scores, expected {len(inputs)}"
        )

    pairs = sorted(
        zip(inputs, scores),
        key=lambda pair: (-pair[1], pair[0].fused_rank, pair[0].chunk_id),
    )
    fused_score_by_id = {
        candidate.chunk_id: candidate.fused_score for candidate in fused.candidates
    }
    ranked = tuple(
        RerankedHit(
            chunk_id=item.chunk_id,
            rerank_rank=position,
            rerank_score=score,
            fused_rank=item.fused_rank,
            fused_score=fused_score_by_id[item.chunk_id],
        )
        for position, (item, score) in enumerate(pairs, start=1)
    )

    return RerankResult(
        ranked=ranked,
        applied=True,
        model=plan.versions.reranker,
        warnings=(),
        stats=RerankStats(
            candidates_in=len(top),
            scored=len(inputs),
            dropped_missing=dropped_missing,
            truncated_passages=truncated_passages,
            batches=math.ceil(len(inputs) / config.max_batch_size),
            fetch_ms=fetch_ms,
            score_ms=score_ms,
        ),
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def _fused_order(plan: SearchPlan, fused: FusedCandidates) -> tuple[RerankedHit, ...]:
    """The fused order as ``RerankResult.ranked``, limited to ``window_k``."""
    return tuple(
        RerankedHit(
            chunk_id=candidate.chunk_id,
            rerank_rank=candidate.fused_rank,
            rerank_score=None,
            fused_rank=candidate.fused_rank,
            fused_score=candidate.fused_score,
        )
        for candidate in fused.candidates[: plan.budgets.window_k]
    )
