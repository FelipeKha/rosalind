"""Tests for the eval dataset schema and JSONL I/O."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rosalind.application.eval.dataset import (
    DatasetFilters,
    GoldEvidence,
    QuestionRecord,
    load_dataset,
    write_dataset,
)


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "q_1",
        "type": "factual",
        "query": "when is the kickoff?",
        "gold": [{"item_id": "e_1"}],
    }
    base.update(overrides)
    return base


def test_valid_record() -> None:
    record = QuestionRecord.model_validate(_record())
    assert record.answerable is True
    assert record.gold == [GoldEvidence(item_id="e_1")]
    assert record.split == "dev"


def test_gold_accepts_message_id_only() -> None:
    record = QuestionRecord.model_validate(
        _record(gold=[{"message_id": "msg-001@example.test"}])
    )
    assert record.gold == [GoldEvidence(message_id="msg-001@example.test")]


def test_gold_accepts_both_ids() -> None:
    record = QuestionRecord.model_validate(
        _record(gold=[{"item_id": "e_1", "message_id": "m_1"}])
    )
    assert record.gold[0].item_id == "e_1"
    assert record.gold[0].message_id == "m_1"


def test_gold_requires_a_reference() -> None:
    with pytest.raises(ValidationError):
        QuestionRecord.model_validate(_record(gold=[{"evidence": "span:0:3"}]))


def test_record_requires_a_query_keyword_or_filter() -> None:
    with pytest.raises(ValidationError):
        QuestionRecord.model_validate(
            {"id": "q", "type": "factual", "gold": [{"item_id": "e"}]}
        )


def test_answerable_requires_gold() -> None:
    with pytest.raises(ValidationError):
        QuestionRecord.model_validate(_record(gold=[]))


def test_unanswerable_must_have_empty_gold() -> None:
    with pytest.raises(ValidationError):
        QuestionRecord.model_validate(
            _record(type="unanswerable", answerable=False, gold=[{"item_id": "e"}])
        )


def test_unanswerable_without_gold_is_valid() -> None:
    record = QuestionRecord.model_validate(
        _record(type="unanswerable", answerable=False, gold=[])
    )
    assert record.answerable is False


def test_extra_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        QuestionRecord.model_validate(_record(bogus=1))


def test_filters_map_to_search_request_filters() -> None:
    filters = DatasetFilters(sender=["mike@turnerroofing.com"], tags=["gmail:Projects"])
    mapped = filters.to_search_request_filters()
    assert mapped.sender == frozenset({"mike@turnerroofing.com"})
    assert mapped.tags == frozenset({"gmail:Projects"})
    assert filters.is_empty() is False


def test_filters_only_record_is_valid() -> None:
    record = QuestionRecord.model_validate(
        _record(query=None, filters={"tags": ["gmail:Finance"]})
    )
    assert record.filters.tags == ["gmail:Finance"]


def test_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "dataset.jsonl"
    records = [QuestionRecord.model_validate(_record())]
    write_dataset(path, records)
    assert load_dataset(path) == records


def test_load_dataset_reports_line_context(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "q", "type": "factual"}\n')
    with pytest.raises(ValueError, match="invalid question"):
        load_dataset(path)
