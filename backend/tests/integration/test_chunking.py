import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence import models
from rosalind.application.services.chunking import EmailChunkingService
from rosalind.domain.search import ChunkingParams
from tests._account import ensure_account

_SENT_AT = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


class _CharCounter:
    def __init__(self, version: str = "char/1"):
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def count(self, text: str) -> int:
        return len(text)

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        return list(range(0, len(text), max_tokens)) + [len(text)]


def _params() -> ChunkingParams:
    return ChunkingParams(
        target_tokens=200,
        max_tokens=480,
        overlap_tokens=20,
        min_tail_tokens=40,
        max_quote_tokens_per_email=1000,
        max_chunks_per_attachment=10,
        include_signature=True,
    )


def _service(counter=None) -> EmailChunkingService:
    return EmailChunkingService(counter=counter or _CharCounter(), params=_params())


def _make_source(uow) -> uuid.UUID:
    account_id = ensure_account(uow).id
    source = composition.source_service.create_source(
        uow, account_id, provider="google", name="google-personal"
    )
    uow.commit()
    return source.id


def _insert_email(
    db_session,
    source_id: uuid.UUID,
    message_id: str,
    *,
    body: str = "hello body",
    quoted: str | None = "> quoted line",
    subject: str = "subject",
    tags: tuple[str, ...] = ("gmail:Inbox",),
    direction: str = "received",
) -> uuid.UUID:
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source_id,
        message_id=message_id,
        message_id_synthetic=False,
        occurred_at=_SENT_AT,
        direction=direction,
        subject=subject,
        has_attachments=False,
        is_trash_or_spam=False,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.flush()

    db_session.add(
        models.EmailParticipant(
            id=uuid.uuid4(),
            message_id=message.id,
            role="from",
            name="Mike Turner",
            addr="mike@turnerroofing.com",
            addr_normalized="mike@turnerroofing.com",
            seq=0,
        )
    )
    db_session.add(
        models.EmailParticipant(
            id=uuid.uuid4(),
            message_id=message.id,
            role="to",
            name="Alex Dupont",
            addr="alex.dupont@gmail.com",
            addr_normalized="alex.dupont@gmail.com",
            seq=0,
        )
    )
    for tag in tags:
        db_session.add(models.EmailTag(id=uuid.uuid4(), message_id=message.id, tag=tag))

    clean_text = body
    segments = [
        models.EmailSegment(
            id=uuid.uuid4(),
            email_id=message.id,
            seq=0,
            kind="new",
            start_offset=0,
            end_offset=len(body),
            quote_depth=0,
        )
    ]
    if quoted:
        start = len(clean_text) + 1
        clean_text = f"{clean_text}\n{quoted}"
        segments.append(
            models.EmailSegment(
                id=uuid.uuid4(),
                email_id=message.id,
                seq=1,
                kind="quoted",
                start_offset=start,
                end_offset=len(clean_text),
                quote_depth=1,
            )
        )

    db_session.add(
        models.EmailText(
            email_id=message.id,
            clean_text=clean_text,
            clean_method="plain",
            status="done",
            stage_version="enrich/1",
            input_sha256="abc",
            segments_digest=f"digest-{message_id}",
        )
    )
    db_session.add_all(segments)
    db_session.commit()
    return message.id


def _chunks(db_session, email_id: uuid.UUID) -> list[models.Chunk]:
    return list(
        db_session.scalars(
            select(models.Chunk)
            .where(models.Chunk.email_id == email_id)
            .order_by(models.Chunk.chunk_kind, models.Chunk.seq)
        ).all()
    )


def test_chunk_writes_and_is_idempotent(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x")

    outcome = _service().chunk(uow, source_id)
    assert outcome.emails_synced == 1
    assert outcome.chunks_written >= 2  # body + quote

    first_chunks = _chunks(db_session, email_id)
    assert first_chunks
    kinds = {c.chunk_kind for c in first_chunks}
    assert "email_body" in kinds
    assert "email_quote" in kinds

    second = _service().chunk(uow, source_id)
    assert second.emails_synced == 0
    assert second.chunks_written == 0
    assert len(_chunks(db_session, email_id)) == len(first_chunks)


def test_text_change_rewrites_chunks(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", body="first version")

    _service().chunk(uow, source_id)
    before = {c.text_sha256 for c in _chunks(db_session, email_id)}

    db_session.execute(
        update(models.EmailText)
        .where(models.EmailText.email_id == email_id)
        .values(clean_text="second version", segments_digest="digest-changed")
    )
    db_session.commit()

    outcome = _service().chunk(uow, source_id)
    assert outcome.chunks_written >= 1
    after = {c.text_sha256 for c in _chunks(db_session, email_id)}
    assert before != after


def test_tag_change_updates_filter_columns(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", tags=("gmail:Inbox",))

    _service().chunk(uow, source_id)
    assert all(c.tags == ["gmail:Inbox"] for c in _chunks(db_session, email_id))

    db_session.add(
        models.EmailTag(id=uuid.uuid4(), message_id=email_id, tag="gmail:Projects")
    )
    db_session.execute(
        update(models.EmailMessage)
        .where(models.EmailMessage.id == email_id)
        .values(updated_at=datetime.now(UTC))
    )
    db_session.commit()

    outcome = _service().chunk(uow, source_id)
    assert outcome.chunks_written >= 1
    assert all(
        set(c.tags) == {"gmail:Inbox", "gmail:Projects"}
        for c in _chunks(db_session, email_id)
    )


def test_version_bump_rebuilds(uow, db_session) -> None:
    source_id = _make_source(uow)
    _insert_email(db_session, source_id, "a@x")

    assert _service(_CharCounter("char/1")).chunk(uow, source_id).chunks_written > 0
    outcome = _service(_CharCounter("char/2")).chunk(uow, source_id)
    assert outcome.chunks_written > 0


def test_cascade_on_email_delete(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x")
    _service().chunk(uow, source_id)
    assert _chunks(db_session, email_id)

    db_session.execute(
        delete(models.EmailMessage).where(models.EmailMessage.id == email_id)
    )
    db_session.commit()

    assert _chunks(db_session, email_id) == []


def test_covered_quote_deletes_only_quote_chunks(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", quoted="> quote text")

    _service().chunk(uow, source_id)
    body_ids = {
        c.id for c in _chunks(db_session, email_id) if c.chunk_kind == "email_body"
    }
    assert body_ids

    # 4C marks the quoted segment as covered by an existing message.
    covering = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source_id,
        message_id="cover@x",
        message_id_synthetic=False,
        occurred_at=_SENT_AT,
        direction="received",
        has_attachments=False,
        is_trash_or_spam=False,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(covering)
    db_session.flush()

    db_session.execute(
        update(models.EmailSegment)
        .where(
            models.EmailSegment.email_id == email_id,
            models.EmailSegment.kind == "quoted",
        )
        .values(covered_by_email_id=covering.id)
    )
    db_session.execute(
        update(models.EmailText)
        .where(models.EmailText.email_id == email_id)
        .values(segments_digest="digest-after-coverage")
    )
    db_session.commit()

    _service().chunk(uow, source_id)

    remaining = _chunks(db_session, email_id)
    assert {c.id for c in remaining} == body_ids
    assert all(c.chunk_kind == "email_body" for c in remaining)
