"""The committed fixture dataset validates against the committed mailbox."""

from __future__ import annotations

from rosalind_eval.corpus import dataset_path, known_item_ids_from_mailbox
from rosalind_eval.dataset import load_dataset
from rosalind_eval.validate import validate_dataset


def test_fixture_dataset_has_no_errors() -> None:
    records = load_dataset(dataset_path())
    issues = validate_dataset(records, known_item_ids=known_item_ids_from_mailbox())
    errors = [issue for issue in issues if issue.level == "error"]
    assert errors == [], errors


def test_fixture_dataset_covers_question_types() -> None:
    records = load_dataset(dataset_path())
    types = {record.type for record in records}
    assert {"factual", "amount_lookup", "exact_token", "unanswerable"} <= types
    assert {"attachment_only", "thread", "multi_hop", "filter_heavy"} <= types


def test_fixture_dataset_has_dev_and_test_splits() -> None:
    records = load_dataset(dataset_path())
    splits = {record.split for record in records}
    assert splits == {"dev", "test"}
