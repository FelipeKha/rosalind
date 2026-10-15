"""The committed eval fixture dataset validates against the fixture mailbox."""

from __future__ import annotations

from rosalind.application.eval.dataset import load_dataset
from rosalind.application.eval.validate import validate_dataset
from tests.eval_support import dataset_path, known_item_ids, resolve_fixture_records


def test_fixture_dataset_has_no_errors() -> None:
    records = resolve_fixture_records()
    issues = validate_dataset(records, known_item_ids=known_item_ids())
    errors = [issue for issue in issues if issue.level == "error"]
    assert errors == [], errors


def test_fixture_gold_resolves_to_canonical_ids() -> None:
    records = resolve_fixture_records()
    known = known_item_ids()
    for record in records:
        for gold in record.gold:
            assert gold.item_id is not None
            assert gold.item_id in known


def test_fixture_dataset_covers_question_types() -> None:
    records = load_dataset(dataset_path())
    types = {record.type for record in records}
    assert {"factual", "amount_lookup", "exact_token", "unanswerable"} <= types
    assert {"attachment_only", "thread", "multi_hop", "filter_heavy"} <= types


def test_fixture_dataset_has_dev_and_test_splits() -> None:
    records = load_dataset(dataset_path())
    splits = {record.split for record in records}
    assert splits == {"dev", "test"}
