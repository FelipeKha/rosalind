"""Tests mapping an app SearchTrace onto an eval QuestionRun (duck-typed)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from rosalind.application.eval.dataset import QuestionRecord
from rosalind.application.eval.mapping import question_run_from_trace

C1, C2 = uuid.uuid4(), uuid.uuid4()
I1, I2 = uuid.uuid4(), uuid.uuid4()


def _question() -> QuestionRecord:
    return QuestionRecord.model_validate(
        {"id": "q1", "type": "factual", "query": "q", "gold": [{"item_id": str(I1)}]}
    )


def _trace() -> SimpleNamespace:
    return SimpleNamespace(
        plan=SimpleNamespace(
            fingerprint="fp",
            mode_effective=SimpleNamespace(value="hybrid"),
            versions=SimpleNamespace(
                index_version="v1",
                embedding_model="bge-m3",
                embedding_version="v1",
                reranker="bge-reranker-v2-m3/v1",
            ),
            budgets=SimpleNamespace(
                lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=25
            ),
        ),
        lexical=SimpleNamespace(
            hits=[SimpleNamespace(chunk_id=C1, email_id=I1, rank=1, score=5.0)]
        ),
        semantic=SimpleNamespace(
            hits=[SimpleNamespace(chunk_id=C2, email_id=I2, rank=1, distance=0.2)],
            complete=False,
            filter_path="ann_iterative",
            scan_limit_hit=True,
        ),
        fused=SimpleNamespace(
            candidates=[
                SimpleNamespace(chunk_id=C1, email_id=I1, fused_rank=1, fused_score=0.5)
            ],
            dropped_by_item_cap=3,
            lexical_used=True,
            semantic_used=True,
        ),
        reranked=SimpleNamespace(
            ranked=[
                SimpleNamespace(
                    chunk_id=C1, rerank_rank=1, rerank_score=0.9, fused_rank=1
                )
            ],
            applied=True,
        ),
        response=SimpleNamespace(
            results=[
                SimpleNamespace(item_id=I1, chunk_id=C1, score=0.9, matched_in="body")
            ],
            warnings=[SimpleNamespace(code=SimpleNamespace(value="rerank_skipped"))],
        ),
        timings_ms={"total_ms": 12.5},
    )


def test_maps_trace_to_run() -> None:
    run = question_run_from_trace(_question(), _trace())
    assert run.plan_fingerprint == "fp"
    assert run.mode_effective == "hybrid"
    assert run.index_version == "v1"
    assert run.embedding_model == "bge-m3"
    assert run.reranker_version == "bge-reranker-v2-m3/v1"
    assert run.budgets["fused_k"] == 40
    assert run.lexical[0].item_id == str(I1)
    assert run.semantic[0].score == 0.2
    assert run.fused[0].score == 0.5
    assert run.reranked[0].item_id == str(I1)  # resolved via fused map
    assert run.reranked[0].score == 0.9
    assert run.results[0].item_id == str(I1)
    assert run.results[0].matched_in == "body"
    assert run.dropped_by_item_cap == 3
    assert run.lexical_used and run.semantic_used
    assert run.rerank_applied is True
    assert run.semantic_complete is False
    assert run.semantic_filter_path == "ann_iterative"
    assert run.semantic_scan_limit_hit is True
    assert run.warnings == ("rerank_skipped",)
    assert run.degraded is True
    assert run.timings_ms == {"total_ms": 12.5}
