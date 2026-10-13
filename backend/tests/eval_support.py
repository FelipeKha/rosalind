"""Shared helpers for eval tests: fixture corpus and a scripted executor."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from pathlib import Path

from rosalind.adapters.outbound.eval.mailbox_source import MailboxPassageSource
from rosalind.application.eval.dataset import QuestionRecord
from rosalind.application.eval.models import (
    FinalResult,
    Passage,
    QuestionRun,
    StageCandidate,
)
from rosalind.domain.email import message_uuid

FIXTURE_SOURCE_ACCOUNT_ID = uuid.UUID("0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")

BUDGETS = {
    "lexical_k": 50,
    "semantic_k": 50,
    "fused_k": 40,
    "rerank_k": 30,
    "window_k": 25,
}


def fixture_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "eval"


def mailbox_path() -> Path:
    return fixture_dir() / "mailbox.mbox"


def dataset_path() -> Path:
    return fixture_dir() / "dataset.jsonl"


def item_id_for(message_id: str) -> str:
    return str(message_uuid(FIXTURE_SOURCE_ACCOUNT_ID, message_id))


def iter_fixture_passages(*, include_trash_spam: bool = False) -> list[Passage]:
    source = MailboxPassageSource(FIXTURE_SOURCE_ACCOUNT_ID)
    return list(
        source.iter_passages(mailbox_path(), include_trash_spam=include_trash_spam)
    )


def known_item_ids() -> frozenset[str]:
    return frozenset(p.item_id for p in iter_fixture_passages(include_trash_spam=True))


# ---------------------------------------------------------------------------
# Scripted executor
# ---------------------------------------------------------------------------


def _candidates(items: Iterable[str]) -> tuple[StageCandidate, ...]:
    return tuple(
        StageCandidate(chunk_id=f"c_{item}", item_id=item, rank=rank, score=1.0)
        for rank, item in enumerate(items, start=1)
    )


def make_run(
    question: QuestionRecord,
    *,
    lexical: Iterable[str] = (),
    semantic: Iterable[str] = (),
    fused: Iterable[str] = (),
    reranked: Iterable[str] = (),
    results: Iterable[str] = (),
    budgets: dict[str, int] | None = None,
    dropped_by_item_cap: int = 0,
    matched_in: str = "body",
    timings_ms: dict[str, float] | None = None,
    **extra: object,
) -> QuestionRun:
    return QuestionRun(
        question_id=question.id,
        question_type=question.type,
        split=question.split,
        answerable=question.answerable,
        gold=tuple(question.gold),
        budgets=dict(budgets or BUDGETS),
        lexical=_candidates(lexical),
        semantic=_candidates(semantic),
        fused=_candidates(fused),
        reranked=_candidates(reranked),
        results=tuple(
            FinalResult(
                item_id=item, chunk_id=f"c_{item}", score=1.0, matched_in=matched_in
            )
            for item in results
        ),
        dropped_by_item_cap=dropped_by_item_cap,
        timings_ms=dict(timings_ms or {"total_ms": 1.0}),
        **extra,  # type: ignore[arg-type]
    )


class ScriptedExecutor:
    """Returns a pre-built ``QuestionRun`` per question id."""

    def __init__(self, runs: dict[str, QuestionRun]) -> None:
        self._runs = runs

    def execute(self, question: QuestionRecord) -> QuestionRun:
        return self._runs[question.id]
