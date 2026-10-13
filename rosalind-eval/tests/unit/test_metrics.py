"""Tests for per-question metrics and ranx parity."""

from __future__ import annotations

from rosalind_eval.dataset import QuestionRecord
from rosalind_eval.metrics import compute_question_metrics, item_order, ranx_metric
from tests.unit._scripted import make_run

BUDGETS = {"lexical_k": 2, "semantic_k": 2, "fused_k": 2, "rerank_k": 2, "window_k": 2}


def _answerable(qid: str, gold: str) -> QuestionRecord:
    return QuestionRecord.model_validate(
        {"id": qid, "type": "factual", "query": "q", "gold": [{"item_id": gold}]}
    )


def test_metrics_for_found_gold() -> None:
    record = _answerable("q1", "g")
    run = make_run(
        record,
        lexical=["g", "x"],
        semantic=["x", "g"],
        fused=["g", "x"],
        reranked=["x", "g"],
        results=["x", "g"],
        budgets=BUDGETS,
    )
    metrics = compute_question_metrics(run)
    assert metrics.recall_lexical == 1.0
    assert metrics.recall_semantic == 1.0
    assert metrics.recall_fused == 1.0
    assert metrics.recall_reranked == 1.0
    assert metrics.recall_window == 1.0
    assert metrics.mrr == 0.5
    assert metrics.hit is True
    assert metrics.branch == "both"


def test_metrics_for_missed_gold() -> None:
    record = _answerable("q1", "g")
    run = make_run(
        record,
        lexical=["x"],
        semantic=["y"],
        fused=["x", "y"],
        reranked=["x", "y"],
        results=["x", "y"],
        budgets=BUDGETS,
    )
    metrics = compute_question_metrics(run)
    assert metrics.recall_fused == 0.0
    assert metrics.mrr == 0.0
    assert metrics.hit is False
    assert metrics.branch == "none"


def test_branch_lexical_only() -> None:
    record = _answerable("q1", "g")
    run = make_run(record, lexical=["g"], semantic=["x"], budgets=BUDGETS)
    assert compute_question_metrics(run).branch == "lexical_only"


def test_unanswerable_metrics_are_none() -> None:
    record = QuestionRecord.model_validate(
        {
            "id": "q1",
            "type": "unanswerable",
            "query": "q",
            "gold": [],
            "answerable": False,
        }
    )
    run = make_run(record, results=["x"], budgets=BUDGETS)
    metrics = compute_question_metrics(run)
    assert metrics.recall_fused is None
    assert metrics.mrr is None
    assert metrics.hit is True


def test_ranx_parity_for_recall_and_ndcg() -> None:
    record = _answerable("q1", "g")
    padded = ["x", "g", *(f"f{i}" for i in range(8))]
    run = make_run(
        record,
        lexical=["g", "x"],
        fused=["g", "x"],
        reranked=["x", "g"],
        results=padded,
        budgets=BUDGETS,
    )
    metrics = compute_question_metrics(run)
    gold = frozenset({"g"})
    assert metrics.recall_fused == ranx_metric(item_order(run.fused), gold, "recall@2")
    assert metrics.mrr == ranx_metric(
        [result.item_id for result in run.results], gold, "mrr"
    )
    assert metrics.ndcg_at_10 == ranx_metric(
        [result.item_id for result in run.results], gold, "ndcg@10"
    )
