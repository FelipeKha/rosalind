import uuid
from dataclasses import replace
from datetime import UTC, datetime

from rosalind.application.ports.search import (
    ChunkAttachmentInput,
    ChunkSegmentInput,
    ChunkWorkItem,
)
from rosalind.application.services.chunking import build_email_chunks
from rosalind.domain.search import ChunkingParams, ChunkKind

_EMAIL_ID = uuid.uuid4()
_SOURCE = uuid.uuid4()
_ATTACHMENT_ID = uuid.uuid4()
_BUILT_AT = datetime(2026, 3, 17, tzinfo=UTC)


class _CharCounter:
    version = "char/1"

    def count(self, text: str) -> int:
        return len(text)

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        return list(range(0, len(text), max_tokens)) + [len(text)]


def _params(**overrides) -> ChunkingParams:
    params = ChunkingParams(
        target_tokens=200,
        max_tokens=480,
        overlap_tokens=20,
        min_tail_tokens=40,
        max_quote_tokens_per_email=1000,
        max_chunks_per_attachment=10,
        include_signature=True,
    )
    return replace(params, **overrides)


def _item(
    *,
    segments: list[tuple[str, str]] | None = None,
    attachments: list[ChunkAttachmentInput] | None = None,
    subject: str = "Roof quote - 12 Elm Street",
    sender_display: str = "Mike Turner <mike@turnerroofing.com>",
    sender_handle: str = "mike@turnerroofing.com",
    has_attachment: bool = False,
) -> ChunkWorkItem:
    parts: list[str] = []
    seg_inputs: list[ChunkSegmentInput] = []
    offset = 0
    for kind, text in segments or []:
        seg_inputs.append(
            ChunkSegmentInput(kind, offset, offset + len(text), None, None, None)
        )
        parts.append(text)
        offset += len(text) + 1  # account for the "\n" separator
    clean_text = "\n".join(parts)
    return ChunkWorkItem(
        email_id=_EMAIL_ID,
        thread_id=None,
        source_account_id=_SOURCE,
        source_account_num=1,
        sent_at=_BUILT_AT,
        sender_handle=sender_handle,
        sender_display=sender_display,
        recipient_handles=("alex.dupont@gmail.com",),
        recipient_display=("Alex Dupont <alex.dupont@gmail.com>",),
        participant_handles=("alex.dupont@gmail.com", "mike@turnerroofing.com"),
        direction="received",
        has_attachment=has_attachment,
        is_trash_or_spam=False,
        tags=("gmail:Inbox",),
        subject=subject,
        clean_text=clean_text,
        text_status="done",
        segments_digest="abc123",
        segments=tuple(seg_inputs),
        attachments=tuple(attachments or []),
    )


def test_roof_email_golden_chunks() -> None:
    body = "Hi Alex, Following our site visit, here is the revised quote: $8,400 including materials and labor for the full roof replacement."
    quote = "> Can you confirm the price? The first quote was $9,200."
    item = _item(
        segments=[("new", body), ("quoted", quote)],
        attachments=[
            ChunkAttachmentInput(
                attachment_id=_ATTACHMENT_ID,
                filename="quote-2026-0412.pdf",
                text="QUOTE #2026-0412 Materials $4,650.00 Labor $3,750.00 Total $8,400.00",
                truncated=False,
                language="en",
                stage_version="attachments/1",
                text_sha256="deadbeef",
                text_ready=True,
            )
        ],
        has_attachment=True,
    )

    drafts, builds = build_email_chunks(
        item, counter=_CharCounter(), params=_params(), version="v1", built_at=_BUILT_AT
    )

    kinds = {d.kind for d in drafts}
    assert ChunkKind.EMAIL_BODY in kinds
    assert ChunkKind.EMAIL_QUOTE in kinds
    assert ChunkKind.ATTACHMENT in kinds

    quote_drafts = [d for d in drafts if d.kind is ChunkKind.EMAIL_QUOTE]
    assert any("$9,200" in d.text_for_display for d in quote_drafts)

    attachment_drafts = [d for d in drafts if d.kind is ChunkKind.ATTACHMENT]
    assert any("Total $8,400.00" in d.text_for_display for d in attachment_drafts)

    assert len(builds) == 3


def test_header_only_body_when_no_body_text() -> None:
    item = _item(segments=[("quoted", "> only quoted text here.")])
    drafts, _builds = build_email_chunks(
        item, counter=_CharCounter(), params=_params(), version="v1", built_at=_BUILT_AT
    )
    body_drafts = [d for d in drafts if d.kind is ChunkKind.EMAIL_BODY]
    assert len(body_drafts) == 1
    assert body_drafts[0].meta == {"header_only": True}
    assert body_drafts[0].text_for_display == ""


def test_quote_cap_truncates_and_marks() -> None:
    long_quote = "> " + ". ".join(f"quoted sentence {i}" for i in range(200))
    item = _item(segments=[("new", "short body"), ("quoted", long_quote)])
    drafts, _ = build_email_chunks(
        item,
        counter=_CharCounter(),
        params=_params(max_quote_tokens_per_email=100),
        version="v1",
        built_at=_BUILT_AT,
    )
    quote_drafts = [d for d in drafts if d.kind is ChunkKind.EMAIL_QUOTE]
    assert any(d.meta.get("truncated") for d in quote_drafts)
    # The quoted source is capped to the earliest 100 tokens.
    combined = "".join(d.text_for_display for d in quote_drafts)
    assert len(combined) <= 100 + _params().overlap_tokens


def test_attachment_cap_limits_chunks() -> None:
    big_text = " ".join(f"attachment word {i}" for i in range(2000))
    item = _item(
        segments=[("new", "body")],
        attachments=[
            ChunkAttachmentInput(
                attachment_id=_ATTACHMENT_ID,
                filename="big.pdf",
                text=big_text,
                truncated=True,
                language=None,
                stage_version="attachments/1",
                text_sha256="feedface",
                text_ready=True,
            )
        ],
        has_attachment=True,
    )
    drafts, _builds = build_email_chunks(
        item,
        counter=_CharCounter(),
        params=_params(max_chunks_per_attachment=3),
        version="v1",
        built_at=_BUILT_AT,
    )
    attachment_drafts = [d for d in drafts if d.kind is ChunkKind.ATTACHMENT]
    assert len(attachment_drafts) == 3


def test_not_ready_attachment_is_skipped() -> None:
    item = _item(
        segments=[("new", "body")],
        attachments=[
            ChunkAttachmentInput(
                attachment_id=_ATTACHMENT_ID,
                filename="pending.pdf",
                text=None,
                truncated=False,
                language=None,
                stage_version=None,
                text_sha256=None,
                text_ready=False,
            )
        ],
        has_attachment=True,
    )
    drafts, _ = build_email_chunks(
        item, counter=_CharCounter(), params=_params(), version="v1", built_at=_BUILT_AT
    )
    assert not [d for d in drafts if d.kind is ChunkKind.ATTACHMENT]
