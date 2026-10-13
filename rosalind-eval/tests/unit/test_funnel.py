"""Tests for the failure funnel classifier."""

from __future__ import annotations

from rosalind_eval.dataset import QuestionRecord
from rosalind_eval.funnel import classify_failure
from tests.unit._scripted import make_run


def _record(*, evidence: str | None = None) -> QuestionRecord:
    gold = {"item_id": "g"}
    if evidence is not None:
        gold["evidence"] = evidence
    return QuestionRecord.model_validate(
        {"id": "q1", "type": "factual", "query": "q", "gold": [gold]}
    )


def test_none_when_found() -> None:
    run = make_run(_record(), results=["g"])
    assert classify_failure(run) is None


def test_not_in_corpus() -> None:
    run = make_run(_record(), lexical=[], semantic=[])
    assert classify_failure(run, known_item_ids=frozenset({"x"})) == "not_in_corpus"


def test_not_chunked() -> None:
    run = make_run(_record())
    assert (
        classify_failure(
            run,
            known_item_ids=frozenset({"g"}),
            chunked_item_ids=frozenset({"x"}),
        )
        == "not_chunked"
    )


def test_missed_by_both_branches() -> None:
    run = make_run(_record(), lexical=["x"], semantic=["y"])
    assert classify_failure(run) == "missed_by_both_branches"


def test_dropped_by_item_cap() -> None:
    run = make_run(_record(), lexical=["g"], fused=["x"], dropped_by_item_cap=2)
    assert classify_failure(run) == "dropped_by_item_cap"


def test_lost_in_fusion() -> None:
    run = make_run(_record(), lexical=["g"], fused=["x"])
    assert classify_failure(run) == "lost_in_fusion"


def test_lost_in_rerank() -> None:
    run = make_run(_record(), lexical=["g"], fused=["g"], reranked=["x"])
    assert classify_failure(run) == "lost_in_rerank"


def test_lost_in_assembly() -> None:
    run = make_run(_record(), lexical=["g"], fused=["g"], reranked=["g"], results=["x"])
    assert classify_failure(run) == "lost_in_assembly"


def test_attachment_evidence_requires_attachment_match() -> None:
    record = _record(evidence="attachment:" + "a" * 64)
    body_only = make_run(
        record,
        lexical=["g"],
        fused=["g"],
        reranked=["g"],
        results=["g"],
        matched_in="body",
    )
    assert classify_failure(body_only) == "lost_in_assembly"
    attached = make_run(
        record,
        lexical=["g"],
        fused=["g"],
        reranked=["g"],
        results=["g"],
        matched_in="attachment",
    )
    assert classify_failure(attached) is None


def test_unanswerable_never_fails() -> None:
    record = QuestionRecord.model_validate(
        {
            "id": "q1",
            "type": "unanswerable",
            "query": "q",
            "gold": [],
            "answerable": False,
        }
    )
    assert classify_failure(make_run(record)) is None
