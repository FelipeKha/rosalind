"""Tests for resolving dataset gold references against a corpus."""

from __future__ import annotations

import uuid

from rosalind.application.eval.dataset import QuestionRecord
from rosalind.application.eval.resolve import resolve_gold

ACCOUNT = uuid.uuid4()


class _Catalog:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = mapping or {}
        self.calls: list[frozenset[str]] = []

    def list_items(self, account_id, import_id=None):  # type: ignore[no-untyped-def]
        return []

    def existing_item_ids(self, account_id, item_ids):  # type: ignore[no-untyped-def]
        return frozenset()

    def resolve_message_ids(self, account_id, message_ids):  # type: ignore[no-untyped-def]
        self.calls.append(message_ids)
        return {
            message_id: item_id
            for message_id, item_id in self._mapping.items()
            if message_id in message_ids
        }


def _q(qid: str, gold: list[dict[str, str]]) -> QuestionRecord:
    return QuestionRecord.model_validate(
        {"id": qid, "type": "factual", "query": "q", "gold": gold}
    )


def test_message_id_is_resolved_to_item_id() -> None:
    catalog = _Catalog({"m1": "e1"})
    records, missing = resolve_gold(
        [_q("q1", [{"message_id": "m1"}])], account_id=ACCOUNT, catalog=catalog
    )
    assert records[0].gold[0].item_id == "e1"
    assert records[0].gold[0].message_id == "m1"
    assert missing == []


def test_message_id_takes_precedence_over_item_id() -> None:
    catalog = _Catalog({"m1": "resolved"})
    records, _ = resolve_gold(
        [_q("q1", [{"item_id": "stale", "message_id": "m1"}])],
        account_id=ACCOUNT,
        catalog=catalog,
    )
    assert records[0].gold[0].item_id == "resolved"


def test_item_id_only_passes_through_without_lookup() -> None:
    catalog = _Catalog()
    records, missing = resolve_gold(
        [_q("q1", [{"item_id": "e1"}])], account_id=ACCOUNT, catalog=catalog
    )
    assert records[0].gold[0].item_id == "e1"
    assert catalog.calls == []
    assert missing == []


def test_missing_message_id_is_reported_and_left_unresolved() -> None:
    catalog = _Catalog({"m1": "e1"})
    records, missing = resolve_gold(
        [
            _q("q1", [{"message_id": "m1"}]),
            _q("q2", [{"message_id": "gone"}]),
        ],
        account_id=ACCOUNT,
        catalog=catalog,
    )
    assert records[0].gold[0].item_id == "e1"
    assert records[1].gold[0].item_id is None
    assert missing == ["gone"]


def test_missing_message_id_reported_once() -> None:
    catalog = _Catalog()
    _, missing = resolve_gold(
        [
            _q("q1", [{"message_id": "gone"}]),
            _q("q2", [{"message_id": "gone"}]),
        ],
        account_id=ACCOUNT,
        catalog=catalog,
    )
    assert missing == ["gone"]
