import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence import models
from rosalind.application.services.attachment_extraction import (
    ATTACHMENT_VERSION,
)
from rosalind.domain.email import AttachmentStatus, AttachmentText, content_sha256
from tests._account import ensure_account


def _make_source(uow) -> uuid.UUID:
    account_id = ensure_account(uow).id
    source = composition.source_service.create_source(
        uow, account_id, provider="google", name="google-personal"
    )
    uow.commit()
    return source.id


def _insert_message(db_session, source_id: uuid.UUID, message_id: str) -> uuid.UUID:
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source_id,
        message_id=message_id,
        message_id_synthetic=False,
        occurred_at=datetime(2026, 3, 17, tzinfo=UTC),
        direction="received",
        text_plain="body",
        content_sha256=content_sha256("body", None),
        has_attachments=False,
        is_trash_or_spam=False,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.flush()
    return message.id


def _insert_attachment(
    db_session,
    message_id: uuid.UUID,
    *,
    sha256: str,
    disposition: str,
    part_index: int,
    declared_mime: str = "application/pdf",
) -> None:
    db_session.add(
        models.EmailAttachment(
            id=uuid.uuid4(),
            message_id=message_id,
            filename="f.pdf",
            declared_mime=declared_mime,
            detected_mime=declared_mime,
            size=100,
            sha256=sha256,
            disposition=disposition,
            storage_key=f"blobs/{sha256[:2]}/{sha256}",
            part_index=part_index,
            status="present",
        )
    )
    db_session.flush()


def test_blob_work_finder_returns_distinct_non_inline_blobs(uow, db_session) -> None:
    source_id = _make_source(uow)
    msg = _insert_message(db_session, source_id, "a@x")
    _insert_attachment(
        db_session, msg, sha256="a" * 64, disposition="attachment", part_index=0
    )
    _insert_attachment(
        db_session, msg, sha256="a" * 64, disposition="attachment", part_index=1
    )
    _insert_attachment(
        db_session, msg, sha256="b" * 64, disposition="inline", part_index=2
    )
    db_session.commit()

    work = uow.attachment_text.list_blob_work(
        source_account_id=source_id, stage_version=ATTACHMENT_VERSION, limit=10
    )

    assert [w.blob_sha256 for w in work] == ["a" * 64]


def test_blob_work_is_idempotent_after_replace(uow, db_session) -> None:
    source_id = _make_source(uow)
    msg = _insert_message(db_session, source_id, "a@x")
    _insert_attachment(
        db_session, msg, sha256="a" * 64, disposition="attachment", part_index=0
    )
    db_session.commit()

    uow.attachment_text.replace_attachment_text(
        result=AttachmentText(
            blob_sha256="a" * 64, status=AttachmentStatus.DONE, text="text"
        ),
        stage_version=ATTACHMENT_VERSION,
    )
    uow.commit()

    rows = db_session.scalars(select(models.AttachmentText)).all()
    assert len(rows) == 1
    assert rows[0].status == "done"

    assert (
        uow.attachment_text.list_blob_work(
            source_account_id=source_id, stage_version=ATTACHMENT_VERSION, limit=10
        )
        == []
    )
