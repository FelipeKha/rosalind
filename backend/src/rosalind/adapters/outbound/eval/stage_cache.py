"""JSON-on-disk stage cache for eval experiment reruns.

Implements the ``StageCache`` port: stores each stage result as JSON under a
cache root so changing a downstream stage never recomputes upstream work. Local
only; never the production database.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from rosalind.application.search.fusion import FusedCandidate, FusedCandidates
from rosalind.application.search.plan import PlanWarning, WarningCode
from rosalind.application.search.rerank import (
    RerankedHit,
    RerankResult,
    RerankStats,
)
from rosalind.application.search.retrieve import LexicalHit, LexicalResult
from rosalind.application.search.semantic import SemanticHit, SemanticResult

__all__ = ["JsonStageCache"]


class JsonStageCache:
    """A ``StageCache`` that persists stage results as JSON files."""

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
