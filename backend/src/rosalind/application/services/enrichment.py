"""Email enrich stage (4A): clean text, segmentation, per-segment language.

Orchestrates the work finder → compute → write loop. The per-message compute
(``prepare_text``) is pure apart from its injected tools, so it can later run in
a process pool without rearchitecting the service; only the main process writes
to the database. Failures become a ``failed`` derived row, never a crashed run.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace

from rosalind.application.ports.enrichment import HtmlParser, LanguageDetector
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.email import CleanMethod, EmailText, SegmentKind
from rosalind.domain.email.html import HtmlDocument
from rosalind.domain.email.segmentation import segment_html, segment_plain
from rosalind.domain.email.text import select_clean_text

ENRICH_VERSION = "enrich/1"

STATUS_DONE = "done"
STATUS_EMPTY = "empty"
STATUS_FAILED = "failed"

DEFAULT_LIMIT = 500
COMMIT_EVERY = 200


@dataclass(frozen=True)
class EnrichOutcome:
    processed: int
    done: int
    empty: int
    failed: int
    budget_exhausted: bool


def prepare_text(
    *,
    text_plain: str | None,
    text_html: str | None,
    html_parser: HtmlParser,
    detector: LanguageDetector,
    min_language_length: int,
) -> EmailText:
    """Compute the derived text and segments for one message (pure + tools)."""
    html_doc: HtmlDocument | None = html_parser.parse(text_html) if text_html else None
    clean_text, method = select_clean_text(text_plain, html_doc)

    if method == "html" and html_doc is not None:
        segments = segment_html(html_doc)
    else:
        segments = segment_plain(clean_text)

    annotated = tuple(
        _annotate_language(segment, clean_text, detector, min_language_length)
        for segment in segments
    )
    return EmailText(
        clean_text=clean_text,
        clean_method=CleanMethod(method),
        segments=annotated,
    )


def _annotate_language(
    segment, clean_text: str, detector: LanguageDetector, min_length: int
):
    if segment.kind is SegmentKind.SIGNATURE:
        return segment
    text = segment.text(clean_text)
    if len(text) < min_length:
        return segment
    language, confidence = detector.detect(text)
    return replace(segment, language=language, language_confidence=confidence)


class EmailEnrichmentService:
    def __init__(
        self,
        html_parser: HtmlParser,
        detector: LanguageDetector,
        *,
        min_language_length: int = 15,
    ):
        self._html_parser = html_parser
        self._detector = detector
        self._min_language_length = min_language_length

    @property
    def stage_version(self) -> str:
        return f"{ENRICH_VERSION}+{self._html_parser.version}+{self._detector.version}"

    def enrich(
        self,
        uow: UnitOfWork,
        source_account_id: uuid.UUID,
        *,
        budget_seconds: float | None = None,
        limit: int = DEFAULT_LIMIT,
        retry_failed: bool = False,
    ) -> EnrichOutcome:
        """Enrich all (or up to ``limit``) messages whose derived row is stale."""
        stage_version = self.stage_version
        deadline = (
            time.monotonic() + budget_seconds if budget_seconds is not None else None
        )

        work = uow.email_enrichment.list_email_work(
            source_account_id=source_account_id,
            stage_version=stage_version,
            limit=limit,
            retry_failed=retry_failed,
        )

        counters = {"processed": 0, "done": 0, "empty": 0, "failed": 0}
        budget_exhausted = False

        for item in work:
            if deadline is not None and time.monotonic() > deadline:
                budget_exhausted = True
                break
            counters["processed"] += 1
            try:
                text = prepare_text(
                    text_plain=item.text_plain,
                    text_html=item.text_html,
                    html_parser=self._html_parser,
                    detector=self._detector,
                    min_language_length=self._min_language_length,
                )
                status = STATUS_DONE if text.clean_text else STATUS_EMPTY
                uow.email_enrichment.replace_email_text(
                    email_id=item.email_id,
                    text=text,
                    status=status,
                    error=None,
                    stage_version=stage_version,
                    input_sha256=item.content_sha256,
                )
                if status == STATUS_DONE:
                    counters["done"] += 1
                else:
                    counters["empty"] += 1
            except Exception as exc:  # noqa: BLE001 - per-record failure isolation
                uow.email_enrichment.replace_email_text(
                    email_id=item.email_id,
                    text=EmailText("", CleanMethod.PLAIN, ()),
                    status=STATUS_FAILED,
                    error=str(exc),
                    stage_version=stage_version,
                    input_sha256=item.content_sha256,
                )
                counters["failed"] += 1

            if counters["processed"] % COMMIT_EVERY == 0:
                uow.commit()

        uow.commit()
        return EnrichOutcome(
            processed=counters["processed"],
            done=counters["done"],
            empty=counters["empty"],
            failed=counters["failed"],
            budget_exhausted=budget_exhausted,
        )
