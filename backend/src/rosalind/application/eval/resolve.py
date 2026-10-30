"""Resolve dataset gold references to a corpus's canonical item ids.

A dataset may key gold by provider ``message_id`` so it stays valid across
imports: the canonical ``email_message.id`` is ``uuid5(NAMESPACE,
f"{source_account_id}:{message_id}")``, so it changes whenever the corpus is
imported under a different source account. Resolving ``message_id`` against the
account's actual corpus makes committed fixtures portable.

This is pure application logic: it depends only on the ``ItemCatalog`` port.
Unresolved ``message_id`` references are reported to the caller (which surfaces
them as run warnings or validation errors) rather than silently scored as misses.
"""

from __future__ import annotations

import uuid

from rosalind.application.eval.dataset import GoldEvidence, QuestionRecord
from rosalind.application.eval.ports import ItemCatalog

__all__ = ["resolve_gold"]


def resolve_gold(
    records: list[QuestionRecord],
    *,
    account_id: uuid.UUID,
    catalog: ItemCatalog,
) -> tuple[list[QuestionRecord], list[str]]:
    """Return records with each gold ``message_id`` filled in as an ``item_id``.

    ``message_id`` takes precedence over a supplied ``item_id``. Gold that only
    carries an ``item_id`` is passed through unchanged. Whenever at least one
    gold entry references a ``message_id``, a single catalog lookup resolves
    them all. Unresolved ``message_id`` values are returned in encounter order
    for the caller to report as missing.
    """
    wanted = {
        gold.message_id
        for record in records
        for gold in record.gold
        if gold.message_id is not None
    }
    if not wanted:
        return records, []

    mapping = catalog.resolve_message_ids(account_id, frozenset(wanted))

    missing: list[str] = []
    seen_missing: set[str] = set()
    resolved: list[QuestionRecord] = []
    for record in records:
        gold = [
            _resolve_entry(entry, mapping, missing, seen_missing)
            for entry in record.gold
        ]
        resolved.append(record.model_copy(update={"gold": gold}))
    return resolved, missing


def _resolve_entry(
    entry: GoldEvidence,
    mapping: dict[str, str],
    missing: list[str],
    seen_missing: set[str],
) -> GoldEvidence:
    if entry.message_id is None:
        return entry
    item_id = mapping.get(entry.message_id)
    if item_id is None:
        if entry.message_id not in seen_missing:
            seen_missing.add(entry.message_id)
            missing.append(entry.message_id)
        return entry.model_copy(update={"item_id": None})
    return entry.model_copy(update={"item_id": item_id})
