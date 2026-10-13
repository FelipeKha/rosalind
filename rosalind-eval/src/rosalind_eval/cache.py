"""Stage-level cache so a downstream experiment never recomputes upstream work.

The eval runner prepares a plan, then calls ``SearchPipeline.run`` with
``resume_from`` + ``cached``. This module decides how far upstream it can resume
and stores the stage results between runs.

Cache key: ``(plan fingerprint inputs, stage versions)``, refined per stage so a
change to a *downstream* stage does not invalidate *upstream* work:

* lexical depends on scope/filters/lexical query/index version and ``lexical_k``;
* semantic additionally on the query vector's model/version and ``semantic_k``;
* fused additionally on the fusion config and ``fused_k``;
* reranked additionally on the reranker version, ``rerank_k`` and rerank text mode.

Only the hashed key is written to disk; results are stored as JSON under a
cache root (local only, never the production database).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rosalind.application.search.fusion import FusedCandidate, FusedCandidates
from rosalind.application.search.overrides import PipelineCache, ResumeStage
from rosalind.application.search.plan import PlanWarning, SearchPlan, WarningCode
from rosalind.application.search.rerank import (
    RerankedHit,
    RerankResult,
    RerankStats,
    RerankTextMode,
)
from rosalind.application.search.retrieve import LexicalHit, LexicalResult
from rosalind.application.search.semantic import SemanticHit, SemanticResult
from rosalind.application.search.trace import SearchTrace

__all__ = ["StageCache", "StageKeys", "cached_run", "select_resume", "stage_keys"]


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


class StageCache:
    """A JSON-on-disk cache of stage results, keyed by a hashed stage key."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def get_lexical(self, key: str) -> LexicalResult | None:
        payload = self._read(key)
        return _decode_lexical(payload["data"]) if payload else None

    def get_semantic(self, key: str) -> SemanticResult | None:
        payload = self._read(key)
        return _decode_semantic(payload["data"]) if payload else None

    def get_fused(self, key: str) -> FusedCandidates | None:
        payload = self._read(key)
        return _decode_fused(payload["data"]) if payload else None

    def get_reranked(self, key: str) -> RerankResult | None:
        payload = self._read(key)
        return _decode_reranked(payload["data"]) if payload else None

    def put_lexical(self, key: str, value: LexicalResult | None) -> None:
        if value is not None:
            self._write(key, "lexical", _encode_lexical(value))

    def put_semantic(self, key: str, value: SemanticResult | None) -> None:
        if value is not None:
            self._write(key, "semantic", _encode_semantic(value))

    def put_fused(self, key: str, value: FusedCandidates | None) -> None:
        if value is not None:
            self._write(key, "fused", _encode_fused(value))

    def put_reranked(self, key: str, value: RerankResult | None) -> None:
        if value is not None:
            self._write(key, "reranked", _encode_reranked(value))

    def _path(self, key: str) -> Path:
        return self._root / f"{key}.json"

    def _read(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        payload: dict[str, Any] = json.loads(path.read_text())
        return payload

    def _write(self, key: str, kind: str, data: Any) -> None:
        self._path(key).write_text(json.dumps({"kind": kind, "data": data}))


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
    trace = await run(
        plan,
        trace_level=trace_level,
        resume_from=resume,
        cached=cached,
        overrides=overrides,
    )
    store_trace(keys, store, trace)
    return trace, resume


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------


def _encode_lexical(value: LexicalResult) -> dict[str, Any]:
    return {
        "hits": [
            {
                "chunk_id": str(hit.chunk_id),
                "email_id": str(hit.email_id),
                "rank": hit.rank,
                "score": hit.score,
            }
            for hit in value.hits
        ],
        "exhausted": value.exhausted,
        "filter_path": value.filter_path,
        "warnings": list(value.warnings),
        "elapsed_ms": value.elapsed_ms,
    }


def _decode_lexical(data: dict[str, Any]) -> LexicalResult:
    return LexicalResult(
        hits=tuple(
            LexicalHit(
                chunk_id=uuid.UUID(hit["chunk_id"]),
                email_id=uuid.UUID(hit["email_id"]),
                rank=hit["rank"],
                score=hit["score"],
            )
            for hit in data["hits"]
        ),
        exhausted=data["exhausted"],
        filter_path=data["filter_path"],
        warnings=tuple(data["warnings"]),
        elapsed_ms=data["elapsed_ms"],
    )


def _encode_semantic(value: SemanticResult) -> dict[str, Any]:
    return {
        "hits": [
            {
                "chunk_id": str(hit.chunk_id),
                "email_id": str(hit.email_id),
                "rank": hit.rank,
                "distance": hit.distance,
            }
            for hit in value.hits
        ],
        "complete": value.complete,
        "filter_path": value.filter_path,
        "scan_limit_hit": value.scan_limit_hit,
        "warnings": list(value.warnings),
        "elapsed_ms": value.elapsed_ms,
    }


def _decode_semantic(data: dict[str, Any]) -> SemanticResult:
    return SemanticResult(
        hits=tuple(
            SemanticHit(
                chunk_id=uuid.UUID(hit["chunk_id"]),
                email_id=uuid.UUID(hit["email_id"]),
                rank=hit["rank"],
                distance=hit["distance"],
            )
            for hit in data["hits"]
        ),
        complete=data["complete"],
        filter_path=data["filter_path"],
        scan_limit_hit=data["scan_limit_hit"],
        warnings=tuple(data["warnings"]),
        elapsed_ms=data["elapsed_ms"],
    )


def _encode_fused(value: FusedCandidates) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "chunk_id": str(candidate.chunk_id),
                "email_id": str(candidate.email_id),
                "fused_score": candidate.fused_score,
                "fused_rank": candidate.fused_rank,
                "lexical_rank": candidate.lexical_rank,
                "lexical_score": candidate.lexical_score,
                "semantic_rank": candidate.semantic_rank,
                "semantic_distance": candidate.semantic_distance,
            }
            for candidate in value.candidates
        ],
        "lexical_used": value.lexical_used,
        "semantic_used": value.semantic_used,
        "dropped_by_item_cap": value.dropped_by_item_cap,
    }


def _decode_fused(data: dict[str, Any]) -> FusedCandidates:
    return FusedCandidates(
        candidates=tuple(
            FusedCandidate(
                chunk_id=uuid.UUID(candidate["chunk_id"]),
                email_id=uuid.UUID(candidate["email_id"]),
                fused_score=candidate["fused_score"],
                fused_rank=candidate["fused_rank"],
                lexical_rank=candidate["lexical_rank"],
                lexical_score=candidate["lexical_score"],
                semantic_rank=candidate["semantic_rank"],
                semantic_distance=candidate["semantic_distance"],
            )
            for candidate in data["candidates"]
        ),
        lexical_used=data["lexical_used"],
        semantic_used=data["semantic_used"],
        dropped_by_item_cap=data["dropped_by_item_cap"],
    )


def _encode_reranked(value: RerankResult) -> dict[str, Any]:
    return {
        "ranked": [
            {
                "chunk_id": str(hit.chunk_id),
                "rerank_rank": hit.rerank_rank,
                "rerank_score": hit.rerank_score,
                "fused_rank": hit.fused_rank,
                "fused_score": hit.fused_score,
            }
            for hit in value.ranked
        ],
        "applied": value.applied,
        "model": value.model,
        "warnings": [
            {
                "code": warning.code.value,
                "message": warning.message,
                "field_name": warning.field_name,
                "suggestion": warning.suggestion,
            }
            for warning in value.warnings
        ],
        "stats": {
            "candidates_in": value.stats.candidates_in,
            "scored": value.stats.scored,
            "dropped_missing": value.stats.dropped_missing,
            "truncated_passages": value.stats.truncated_passages,
            "batches": value.stats.batches,
            "fetch_ms": value.stats.fetch_ms,
            "score_ms": value.stats.score_ms,
        },
        "elapsed_ms": value.elapsed_ms,
    }


def _decode_reranked(data: dict[str, Any]) -> RerankResult:
    return RerankResult(
        ranked=tuple(
            RerankedHit(
                chunk_id=uuid.UUID(hit["chunk_id"]),
                rerank_rank=hit["rerank_rank"],
                rerank_score=hit["rerank_score"],
                fused_rank=hit["fused_rank"],
                fused_score=hit["fused_score"],
            )
            for hit in data["ranked"]
        ),
        applied=data["applied"],
        model=data["model"],
        warnings=tuple(
            PlanWarning(
                code=WarningCode(warning["code"]),
                message=warning["message"],
                field_name=warning["field_name"],
                suggestion=warning["suggestion"],
            )
            for warning in data["warnings"]
        ),
        stats=RerankStats(**data["stats"]),
        elapsed_ms=data["elapsed_ms"],
    )
