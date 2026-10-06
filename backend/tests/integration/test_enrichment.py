import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from rosalind.adapters import composition
from rosalind.adapters.outbound.enrichment.html import SelectolaxHtmlParser
from rosalind.adapters.outbound.persistence import models
from rosalind.application.services.enrichment import EmailEnrichmentService
from rosalind.domain.email import CleanMethod, EmailText, content_sha256
from tests._account import ensure_account


class _FakeDetector:
    version = "fake/1"

    def detect(self, text: str) -> tuple[str | None, float | None]:
        return ("en", 0.99)


def _make_source(uow) -> uuid.UUID:
    account_id = ensure_account(uow).id
    source = composition.source_service.create_source(
        uow, account_id, provider="google", name="google-personal"
    )
    uow.commit()
    return source.id


def _insert_message(
    db_session,
    source_account_id: uuid.UUID,
    message_id: str,
    text_plain: str,
    text_html: str | None = None,
) -> uuid.UUID:
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source_account_id,
        message_id=message_id,
        message_id_synthetic=False,
        occurred_at=datetime(2026, 3, 17, tzinfo=UTC),
        direction="received",
        subject="hello",
        text_plain=text_plain,
        text_html=text_html,
        content_sha256=content_sha256(text_plain, text_html),
        has_attachments=False,
        is_trash_or_spam=False,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.commit()
    return message.id


def _service() -> EmailEnrichmentService:
    return EmailEnrichmentService(
        html_parser=SelectolaxHtmlParser(),
        detector=_FakeDetector(),
    )


def test_enrich_writes_derived_text_and_segments(uow, db_session) -> None:
    source_id = _make_source(uow)
    _insert_message(db_session, source_id, "a@x", "Hello\n> quoted\n")

    outcome = _service().enrich(uow, source_id)

    assert outcome.done == 1
    assert outcome.failed == 0

    texts = db_session.scalars(select(models.EmailText)).all()
    assert len(texts) == 1
    assert texts[0].status == "done"
    assert texts[0].clean_text == "Hello\n> quoted\n"

    segments = db_session.scalars(select(models.EmailSegment)).all()
    assert {s.kind for s in segments} == {"new", "quoted"}


def test_enrich_is_idempotent(uow, db_session) -> None:
    source_id = _make_source(uow)
    _insert_message(db_session, source_id, "a@x", "Hello\n")

    service = _service()
    assert service.enrich(uow, source_id).done == 1
    assert service.enrich(uow, source_id).processed == 0


def test_enrich_reprocesses_when_content_sha256_changes(uow, db_session) -> None:
    source_id = _make_source(uow)
    message_id = _insert_message(db_session, source_id, "a@x", "Hello\n")

    service = _service()
    assert service.enrich(uow, source_id).done == 1

    db_session.execute(
        update(models.EmailMessage)
        .where(models.EmailMessage.id == message_id)
        .values(
            text_plain="Changed\n",
            content_sha256=content_sha256("Changed\n", None),
        )
    )
    db_session.commit()

    outcome = service.enrich(uow, source_id)
    assert outcome.processed == 1
    assert outcome.done == 1


def test_enrich_reprocesses_when_stage_version_changes(uow, db_session) -> None:
    source_id = _make_source(uow)
    _insert_message(db_session, source_id, "a@x", "Hello\n")

    first = EmailEnrichmentService(
        html_parser=SelectolaxHtmlParser(), detector=_FakeDetector()
    )
    assert first.enrich(uow, source_id).done == 1

    class _NewDetector:
        version = "fake/2"

        def detect(self, text):
            return ("en", 0.99)

    second = EmailEnrichmentService(
        html_parser=SelectolaxHtmlParser(), detector=_NewDetector()
    )
    assert second.enrich(uow, source_id).processed == 1


def test_work_finder_treats_null_content_sha256_as_stale(uow, db_session) -> None:
    source_id = _make_source(uow)
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source_id,
        message_id="nullhash@x",
        message_id_synthetic=False,
        occurred_at=datetime(2026, 3, 17, tzinfo=UTC),
        direction="received",
        text_plain="Hello\n",
        text_html=None,
        content_sha256=None,
        has_attachments=False,
        is_trash_or_spam=False,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.commit()

    service = _service()
    first = service.enrich(uow, source_id)
    assert first.processed == 1

    second = service.enrich(uow, source_id)
    assert second.processed == 0


def test_failed_row_not_retried_unless_forced(uow, db_session) -> None:
    source_id = _make_source(uow)
    message_id = _insert_message(db_session, source_id, "a@x", "Hello\n")

    # Mark the derived row as failed with the current stage version.
    service = _service()
    stage = service.stage_version
    uow.email_enrichment.replace_email_text(
        email_id=message_id,
        text=EmailText("", CleanMethod.PLAIN, ()),
        status="failed",
        error="boom",
        stage_version=stage,
        input_sha256=content_sha256("Hello\n", None),
        segments_digest=None,
    )
    uow.commit()

    assert service.enrich(uow, source_id).processed == 0
    assert service.enrich(uow, source_id, retry_failed=True).processed == 1
