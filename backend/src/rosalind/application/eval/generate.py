"""Draft-question generation logic.

Given a passage from a mailbox, a local LLM writes a natural question whose
answer is in that message. The result is a ``draft`` ``QuestionRecord`` with the
passage's item id as gold; nothing counts toward metrics until a human marks it
``reviewed``.

The LLM is behind the ``QuestionLLM`` port so tests run deterministically with a
fake and production use stays local (Ollama, adapter in
``rosalind.adapters.outbound.eval.ollama``).
"""

from __future__ import annotations

from collections.abc import Iterable

from rosalind.application.eval.dataset import (
    DatasetFilters,
    GoldEvidence,
    QuestionRecord,
    Split,
)
from rosalind.application.eval.models import DraftQuestion, Passage
from rosalind.application.eval.ports import QuestionLLM

__all__ = [
    "SYSTEM_PROMPT",
    "build_prompt",
    "generate_questions",
]

SYSTEM_PROMPT = (
    "You write short, natural search questions about a person's email archive. "
    "The question must be answerable using only the given email, phrased the way "
    "the mailbox owner would ask it (first person, no email addresses). Return a "
    "question, its type, a short exact answer taken from the email, and optional "
    "exact-match keywords (names, ids, amounts). Never invent facts not present."
)


def build_prompt(passage: Passage) -> str:
    """Render the passage into a user prompt. Contains email text (local only)."""
    attachment = (
        f"\n[attachment sha256: {passage.attachment_sha256}]"
        if passage.attachment_sha256
        else ""
    )
    subject = passage.subject or "(no subject)"
    return f"Subject: {subject}{attachment}\n\n{passage.text}"


def generate_questions(
    passages: Iterable[Passage],
    llm: QuestionLLM,
    *,
    split: Split = "dev",
) -> list[QuestionRecord]:
    """Write one draft question per passage."""
    records: list[QuestionRecord] = []
    for index, passage in enumerate(passages, start=1):
        draft: DraftQuestion = llm.generate(passage)
        answerable = draft.type != "unanswerable"
        gold = [GoldEvidence(item_id=passage.item_id)] if answerable else []
        records.append(
            QuestionRecord(
                id=f"q_{index:03d}",
                type=draft.type,
                query=draft.query,
                keywords=draft.keywords,
                filters=DatasetFilters(),
                gold=gold,
                answer=draft.answer,
                answerable=answerable,
                split=split,
                status="draft",
            )
        )
    return records
