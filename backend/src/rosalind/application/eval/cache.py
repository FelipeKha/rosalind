"""Stage-cache key logic so a downstream experiment never recomputes upstream.

The eval runner prepares a plan, then calls ``SearchPipeline.run`` with
``resume_from`` + ``cached``. This module decides how far upstream it can resume
and defines the per-stage cache keys. The actual storage/serialization is an
outbound adapter implementing the ``StageCache`` port.

Cache key is per stage so a *downstream* change does not invalidate *upstream*
work: lexical depends on scope/filters/lexical query/index version and
``lexical_k``; semantic adds the query vector's model/version and ``semantic_k``;
fused adds the fusion config and ``fused_k``; reranked adds the reranker version,
``rerank_k`` and the rerank text mode.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from rosalind.application.eval.ports import StageCache
from rosalind.application.search.overrides import PipelineCache, ResumeStage
from rosalind.application.search.plan import SearchPlan
from rosalind.application.search.rerank import RerankTextMode
from rosalind.application.search.trace import SearchTrace

__all__ = [
    "StageKeys",
    "cached_run",
    "load_cache",
    "select_resume",
    "stage_keys",
    "store_trace",
]


@dataclass(frozen=True, slots=True)
class StageKeys:
    lexical: str
    semantic: str
    fused: str
    reranked: str


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def stage_keys(
    plan: SearchPlan, *, rerank_text_mode: RerankTextMode | None = None
) -> StageKeys:
    """Per-stage cache keys derived from the plan's stage-specific inputs."""
    base: dict[str, Any] = {
        "account": str(plan.scope.account_id),
        "sources": sorted(str(s) for s in plan.scope.source_account_ids),
        "filters": plan.filters.to_echo(),
        "index_version": plan.versions.index_version,
    }
    query = plan.query
    lexical_payload = {
        **base,
        "embedding_model": plan.versions.embedding_model,
        "embedding_version": plan.versions.embedding_version,
        "terms": list(query.lexical.terms) if query.lexical else None,
        "phrases": list(query.lexical.phrases) if query.lexical else None,
        "lexical_k": plan.budgets.lexical_k,
    }
    lexical_key = _hash(lexical_payload)

    semantic_payload = {
        **base,
        "embedding_model": plan.versions.embedding_model,
        "embedding_version": plan.versions.embedding_version,
        "semantic_text": query.semantic_text,
        "vector": (
            {
                "model": query.vector.model,
                "version": query.vector.model_version,
                "digest": query.vector.digest,
            }
            if query.vector
            else None
        ),
        "semantic_k": plan.budgets.semantic_k,
    }
    semantic_key = _hash(semantic_payload)

    fusion = plan.fusion
    fused_key = _hash(
        {
            "lexical": lexical_key,
            "semantic": semantic_key,
            "strategy": fusion.strategy.value,
            "rrf_k": fusion.rrf_k,
            "lexical_weight": fusion.lexical_weight,
            "semantic_weight": fusion.semantic_weight,
            "convex_alpha": fusion.convex_alpha,
            "max_chunks_per_item": fusion.max_chunks_per_item,
            "fused_k": plan.budgets.fused_k,
        }
    )
    reranked_key = _hash(
        {
            "fused": fused_key,
            "reranker": plan.versions.reranker,
            "rerank_k": plan.budgets.rerank_k,
            "text_mode": rerank_text_mode.value if rerank_text_mode else None,
        }
    )
    return StageKeys(
        lexical=lexical_key,
        semantic=semantic_key,
        fused=fused_key,
        reranked=reranked_key,
    )


def select_resume(plan: SearchPlan, cache: PipelineCache) -> ResumeStage:
    """The latest stage whose upstream inputs are fully cached."""
    if cache.reranked is not None:
        return ResumeStage.ASSEMBLE
    if cache.fused is not None:
        return ResumeStage.RERANK
    if _branches_ready(plan, cache):
        return ResumeStage.FUSE
    if cache.lexical is not None:
        return ResumeStage.SEMANTIC
    return ResumeStage.LEXICAL


def _branches_ready(plan: SearchPlan, cache: PipelineCache) -> bool:
    if plan.query.lexical is not None and cache.lexical is None:
        return False
    return not (plan.query.vector is not None and cache.semantic is None)


def load_cache(keys: StageKeys, store: StageCache) -> PipelineCache:
    return PipelineCache(
        lexical=store.get_lexical(keys.lexical),
        semantic=store.get_semantic(keys.semantic),
        fused=store.get_fused(keys.fused),
        reranked=store.get_reranked(keys.reranked),
    )


def store_trace(keys: StageKeys, store: StageCache, trace: SearchTrace) -> None:
    store.put_lexical(keys.lexical, trace.lexical)
    store.put_semantic(keys.semantic, trace.semantic)
    store.put_fused(keys.fused, trace.fused)
    store.put_reranked(keys.reranked, trace.reranked)


async def cached_run(
    run: Any,
    plan: SearchPlan,
    store: StageCache,
    *,
    trace_level: str = "full",
    overrides: Any | None = None,
) -> tuple[SearchTrace, ResumeStage]:
    """Run ``plan`` through ``run`` (``SearchPipeline.run`` / ``SearchService.run``).

    Applies ``overrides`` for the effective plan used to key the cache, reuses
    cached upstream stage results, resumes from the latest available stage, then
    stores this run's results for the next experiment. Returns the trace and the
    stage it resumed from.
    """
    effective = overrides.apply(plan) if overrides is not None else plan
    text_mode = overrides.rerank_text_mode if overrides is not None else None
    keys = stage_keys(effective, rerank_text_mode=text_mode)
    cached = load_cache(keys, store)
    resume = select_resume(effective, cached)
    trace: SearchTrace = await run(
        plan,
        trace_level=trace_level,
        resume_from=resume,
        cached=cached,
        overrides=overrides,
    )
    store_trace(keys, store, trace)
    return trace, resume
