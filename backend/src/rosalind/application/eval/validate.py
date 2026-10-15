"""Dataset validation beyond the Pydantic schema.

Schema (types, required fields, answerable/gold consistency) is enforced at load
time in ``dataset``. This module adds the cross-record and corpus checks:

* question ids are unique;
* the ``dev`` and ``test`` splits do not share any gold ``item_id`` (no leakage);
* every gold ``item_id`` exists in the corpus (when a known-id set is supplied);
* aggregation questions are flagged as not scored for retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rosalind.application.eval.dataset import GoldEvidence, QuestionRecord

__all__ = ["ValidationIssue", "validate_dataset"]

Level = Literal["error", "warning"]


@dataclass(frozen=True)
class ValidationIssue:
    level: Level
    code: str
    message: str
    question_id: str | None = None


def validate_dataset(
    records: list[QuestionRecord],
    *,
    known_item_ids: frozenset[str] | None = None,
) -> list[ValidationIssue]:
    """Return all validation issues found. An empty list means the set is valid."""
    issues: list[ValidationIssue] = []
    issues.extend(_check_unique_ids(records))
    issues.extend(_check_split_leakage(records))
    if known_item_ids is not None:
        issues.extend(_check_items_exist(records, known_item_ids))
    issues.extend(_check_aggregation(records))
    return issues


def _check_unique_ids(records: list[QuestionRecord]) -> list[ValidationIssue]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for record in records:
        if record.id in seen:
            duplicates.append(record.id)
        seen.add(record.id)
    return [
        ValidationIssue("error", "duplicate_id", f"duplicate question id {qid!r}", qid)
        for qid in duplicates
    ]


def _check_split_leakage(records: list[QuestionRecord]) -> list[ValidationIssue]:
    by_split: dict[str, set[str]] = {"dev": set(), "test": set()}
    for record in records:
        by_split[record.split].update(_gold_key(item) for item in record.gold)
    overlap = by_split["dev"] & by_split["test"]
    return [
        ValidationIssue(
            "error",
            "split_leakage",
            f"gold item {item_id!r} appears in both dev and test",
        )
        for item_id in sorted(overlap)
    ]


def _check_items_exist(
    records: list[QuestionRecord], known_item_ids: frozenset[str]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for record in records:
        for gold in record.gold:
            if gold.item_id is None or gold.item_id in known_item_ids:
                continue
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_item",
                    f"gold item {gold.item_id!r} is not in the corpus",
                    record.id,
                )
            )
    return issues


def _gold_key(gold: GoldEvidence) -> str:
    """Stable per-entry key for leakage checks, before or after resolution."""
    return gold.item_id or gold.message_id or ""


def _check_aggregation(records: list[QuestionRecord]) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            "warning",
            "aggregation_not_scored",
            "aggregation questions are checked for tool routing only, not retrieval",
            record.id,
        )
        for record in records
        if record.type == "aggregation"
    ]
