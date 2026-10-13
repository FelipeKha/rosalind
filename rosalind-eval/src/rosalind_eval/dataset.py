"""Dataset format for rosalind-eval: JSONL, one record per question.

A dataset is a git-versionable list of questions. Gold labels reference
canonical ``item_id`` values (never ``chunk_id``, which changes when chunking
changes), optionally with a text-span or attachment-blob ``evidence`` hint.

The file contains only identifiers, never email bodies or answers extracted
from private mail, so it is safe to commit. See ``validate.py`` for the checks
applied on top of the schema.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from rosalind.application.search import Direction, SearchRequestFilters

__all__ = [
    "DatasetFilters",
    "GoldEvidence",
    "QuestionRecord",
    "QuestionType",
    "Split",
    "Status",
    "load_dataset",
    "write_dataset",
]

QuestionType = Literal[
    "factual",
    "amount_lookup",
    "exact_token",
    "filter_heavy",
    "attachment_only",
    "thread",
    "multi_hop",
    "unanswerable",
    "aggregation",
]

Split = Literal["dev", "test"]
Status = Literal["draft", "reviewed", "too_easy", "bad"]


class GoldEvidence(BaseModel):
    """One expected source item for a question.

    ``item_id`` is the canonical message id. ``evidence`` is an optional hint:
    ``attachment:<blob_sha256>`` names a specific attachment, ``span:<start>:<end>``
    a character range. It is never required and never a ``chunk_id``.
    """

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1)
    evidence: str | None = None


class DatasetFilters(BaseModel):
    """Search filters for a question. Mirrors the search filter vocabulary."""

    model_config = ConfigDict(extra="forbid")

    sender: list[str] | None = None
    recipient: list[str] | None = None
    participant: list[str] | None = None
    direction: Literal["received", "sent", "self", "unknown"] | None = None
    date_from: date | None = None
    date_before: date | None = None
    tags: list[str] | None = None
    exclude_tags: list[str] | None = None
    has_attachment: bool | None = None
    thread_of: uuid.UUID | None = None
    language: list[str] | None = None
    source_accounts: list[uuid.UUID] | None = None
    include_trash_spam: bool = False

    def is_empty(self) -> bool:
        return not any(
            (
                self.sender,
                self.recipient,
                self.participant,
                self.direction,
                self.date_from,
                self.date_before,
                self.tags,
                self.exclude_tags,
                self.has_attachment is not None,
                self.thread_of,
                self.language,
                self.source_accounts,
            )
        )

    def to_search_request_filters(self) -> SearchRequestFilters:
        """Map onto the app's ``SearchRequestFilters`` for the runner."""
        return SearchRequestFilters(
            sender=frozenset(self.sender or ()),
            recipient=frozenset(self.recipient or ()),
            participant=frozenset(self.participant or ()),
            direction=Direction(self.direction) if self.direction else None,
            date_from=self.date_from,
            date_before=self.date_before,
            tags=frozenset(self.tags or ()),
            exclude_tags=frozenset(self.exclude_tags or ()),
            has_attachment=self.has_attachment,
            thread_of=self.thread_of,
            language=frozenset(self.language or ()),
            source_accounts=frozenset(self.source_accounts or ()),
            include_trash_spam=self.include_trash_spam,
        )


class QuestionRecord(BaseModel):
    """One evaluation question."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: QuestionType
    query: str | None = None
    keywords: str | None = None
    filters: DatasetFilters = Field(default_factory=DatasetFilters)
    gold: list[GoldEvidence] = Field(default_factory=list)
    answer: str | None = None
    answerable: bool = True
    split: Split = "dev"
    status: Status = "draft"

    @model_validator(mode="after")
    def _check_consistency(self) -> QuestionRecord:
        if not (self.query or self.keywords or not self.filters.is_empty()):
            raise ValueError("at least one of query, keywords, or a filter is required")
        if self.type == "unanswerable":
            if self.answerable:
                raise ValueError("an unanswerable question must set answerable: false")
            if self.gold:
                raise ValueError(
                    "an unanswerable question must have an empty gold list"
                )
        if not self.answerable and self.gold:
            raise ValueError("an unanswerable question must have an empty gold list")
        if self.answerable and not self.gold:
            raise ValueError("an answerable question needs at least one gold item")
        return self


def load_dataset(path: str | Path) -> list[QuestionRecord]:
    """Load and schema-validate a JSONL dataset."""
    dataset_path = Path(path)
    records: list[QuestionRecord] = []
    with dataset_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{dataset_path}:{line_number}: invalid JSON: {exc}"
                ) from exc
            try:
                records.append(QuestionRecord.model_validate(raw))
            except Exception as exc:
                raise ValueError(
                    f"{dataset_path}:{line_number}: invalid question: {exc}"
                ) from exc
    return records


def write_dataset(path: str | Path, records: list[QuestionRecord]) -> None:
    """Write records as JSONL."""
    dataset_path = Path(path)
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    with dataset_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json(exclude_none=True) + "\n")
