"""Tests for the draft-question generator (with a deterministic fake LLM)."""

from __future__ import annotations

from rosalind_eval.corpus import Passage, item_id_for, iter_passages
from rosalind_eval.generate import DraftQuestion, build_prompt, generate_questions


class FakeLLM:
    def __init__(self, qtype: str = "factual") -> None:
        self._qtype = qtype
        self.seen: list[str] = []

    def generate(self, passage: Passage) -> DraftQuestion:
        self.seen.append(passage.message_id)
        return DraftQuestion(
            query=f"What does {passage.message_id} say?",
            type=self._qtype,  # type: ignore[arg-type]
            answer="something",
            keywords="exact-token",
        )


def _passages() -> list[Passage]:
    return [
        Passage(
            item_id=item_id_for(f"msg-00{i}@example.test"),
            message_id=f"msg-00{i}@example.test",
            subject=f"Subject {i}",
            text=f"Body number {i}",
            attachment_sha256=None,
        )
        for i in (1, 2, 3)
    ]


def test_generate_produces_draft_records() -> None:
    records = generate_questions(_passages(), FakeLLM())
    assert [r.id for r in records] == ["q_001", "q_002", "q_003"]
    assert all(r.status == "draft" for r in records)
    assert all(r.answerable for r in records)
    assert records[0].gold[0].item_id == item_id_for("msg-001@example.test")
    assert records[0].keywords == "exact-token"


def test_unanswerable_draft_has_no_gold() -> None:
    records = generate_questions(_passages()[:1], FakeLLM(qtype="unanswerable"))
    assert records[0].answerable is False
    assert records[0].gold == []


def test_generate_from_fixture_mailbox() -> None:
    passages = list(iter_passages())[:5]
    records = generate_questions(passages, FakeLLM())
    assert len(records) == 5
    assert records[0].gold[0].item_id == passages[0].item_id


def test_build_prompt_marks_attachment() -> None:
    passage = Passage(
        item_id="e",
        message_id="m",
        subject="Quote",
        text="Body",
        attachment_sha256="a" * 64,
    )
    prompt = build_prompt(passage)
    assert "Quote" in prompt
    assert "Body" in prompt
    assert "attachment sha256" in prompt


def test_build_prompt_without_attachment() -> None:
    passage = Passage(
        item_id="e", message_id="m", subject=None, text="Body", attachment_sha256=None
    )
    prompt = build_prompt(passage)
    assert "(no subject)" in prompt
    assert "attachment sha256" not in prompt
