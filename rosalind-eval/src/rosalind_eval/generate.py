"""Draft-question generator.

Given a passage from the fixture mailbox, a local LLM writes a natural question
whose answer is in that message. The result is a ``draft`` ``QuestionRecord``
with the passage's item id as gold; nothing counts toward metrics until a human
marks it ``reviewed`` (the plan's labeling workflow).

The LLM is behind ``QuestionLLM`` so tests run deterministically with a fake and
so production use stays local (Ollama, via ``llm.make_ollama_llm``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from rosalind_eval.corpus import Passage
from rosalind_eval.dataset import (
    DatasetFilters,
    GoldEvidence,
    QuestionRecord,
    QuestionType,
    Split,
)

__all__ = [
    "SYSTEM_PROMPT",
    "DraftQuestion",
    "QuestionLLM",
    "build_prompt",
    "generate_questions",
]


class DraftQuestion(BaseModel):
    """Structured output the LLM must return for one passage."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    type: QuestionType
    answer: str = Field(min_length=1)
    keywords: str | None = None


class QuestionLLM(Protocol):
    def generate(self, passage: Passage) -> DraftQuestion:
        """Write one question answerable by ``passage``."""


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
        draft = llm.generate(passage)
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
