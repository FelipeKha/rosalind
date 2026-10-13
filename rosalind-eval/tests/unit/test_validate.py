"""Tests for cross-record dataset validation."""

from __future__ import annotations

from rosalind_eval.dataset import QuestionRecord
from rosalind_eval.validate import validate_dataset


def _q(
    qid: str,
    *,
    item: str | None = "e_1",
    split: str = "dev",
    qtype: str = "factual",
    answerable: bool = True,
) -> QuestionRecord:
    return QuestionRecord.model_validate(
        {
            "id": qid,
            "type": qtype,
            "query": "q",
            "gold": [{"item_id": item}] if item else [],
            "answerable": answerable,
            "split": split,
        }
    )


def test_clean_dataset_has_no_errors() -> None:
    issues = validate_dataset([_q("a"), _q("b", item="e_2", split="test")])
    assert [i for i in issues if i.level == "error"] == []


def test_duplicate_ids_are_errors() -> None:
    issues = validate_dataset([_q("a"), _q("a", item="e_2")])
    assert any(i.code == "duplicate_id" for i in issues)


def test_split_leakage_is_an_error() -> None:
    issues = validate_dataset([_q("a", item="e_1"), _q("b", item="e_1", split="test")])
    assert any(i.code == "split_leakage" for i in issues)


def test_missing_item_is_an_error_when_corpus_provided() -> None:
    issues = validate_dataset([_q("a", item="e_1")], known_item_ids=frozenset({"e_2"}))
    assert any(i.code == "missing_item" for i in issues)


def test_existing_item_passes() -> None:
    issues = validate_dataset([_q("a", item="e_1")], known_item_ids=frozenset({"e_1"}))
    assert [i for i in issues if i.level == "error"] == []


def test_aggregation_is_a_warning() -> None:
    issues = validate_dataset([_q("a", qtype="aggregation")])
    assert any(i.code == "aggregation_not_scored" for i in issues)
    assert all(i.level != "error" for i in issues)
