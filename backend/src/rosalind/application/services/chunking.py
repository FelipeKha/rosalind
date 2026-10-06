"""Email chunk stage: cut derived text into ``search.chunk`` rows.

Orchestrates the work finder → compute → write loop. The per-email compute
(``build_email_chunks``) is pure apart from the injected tokenizer, so it can be
tested without a database. Only the service writes, in batches with per-email
failure isolation, so a disconnect stops at a batch boundary.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from rosalind.application.ports.search import (
    ChunkBuildRow,
    ChunkWorkItem,
    TokenCounter,
)
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.search import (
    ChunkDraft,
    ChunkingParams,
    ChunkKind,
    PrefixContext,
    build_prefix,
    chunk_id,
    chunk_text,
    index_version,
    truncate_to_tokens,
)

DEFAULT_LIMIT = 500
COMMIT_EVERY = 200

_STATUS_DONE = "done"
_STATUS_FAILED = "failed"

_BODY_SEGMENT_KINDS = ("new", "forwarded")

_SEPARATOR = "\n"


@dataclass(frozen=True)
class ChunkOutcome:
    emails_synced: int
    chunks_written: int
    chunks_unchanged: int
    skipped_not_ready: int
    failed: int


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _body_text(item: ChunkWorkItem, params: ChunkingParams) -> str:
    kinds = set(_BODY_SEGMENT_KINDS)
    if params.include_signature:
        kinds.add("signature")
    clean = item.clean_text or ""
    return "".join(
        clean[seg.start_offset : seg.end_offset]
        for seg in item.segments
        if seg.kind in kinds
    )


def _quote_segments(item: ChunkWorkItem) -> list:
    return [
        seg
        for seg in item.segments
        if seg.kind == "quoted" and seg.covered_by_email_id is None
    ]


def _dominant_language(segments, clean_text: str) -> str | None:
    totals: dict[str, int] = {}
    for seg in segments:
        if not seg.language:
            continue
        totals[seg.language] = totals.get(seg.language, 0) + (
            seg.end_offset - seg.start_offset
        )
    if not totals:
        return None
    return max(totals, key=lambda lang: totals[lang])


def _prefix_context(item: ChunkWorkItem) -> PrefixContext:
    return PrefixContext(
        subject=item.subject,
        sender=item.sender_display,
        recipients=item.recipient_display,
        date=item.sent_at,
        attachment_filenames=tuple(
            att.filename for att in item.attachments if att.filename
        ),
    )


def _chunk_source(
    *,
    item: ChunkWorkItem,
    kind: ChunkKind,
    source_text: str,
    prefix: str,
    counter: TokenCounter,
    params: ChunkingParams,
    version: str,
    built_at: datetime,
    attachment_id: uuid.UUID | None,
    language: str | None,
    meta: dict,
    source_digest: str | None,
) -> tuple[list[ChunkDraft], ChunkBuildRow]:
    budget = params.max_tokens - counter.count(prefix) - 1
    if budget <= 0:
        budget = 1
    chunk_params = replace(
        params,
        target_tokens=min(params.target_tokens, budget),
        max_tokens=budget,
    )

    spans = chunk_text(source_text, counter=counter, params=chunk_params)
    if not spans:
        draft = _header_only(item, kind, prefix, version, attachment_id)
        return [draft], _build_row(
            item, kind, attachment_id, version, built_at, 1, source_digest
        )

    drafts: list[ChunkDraft] = []
    for span in spans:
        text = source_text[span.start : span.end]
        indexed = f"{prefix}{_SEPARATOR}{text}"
        drafts.append(
            ChunkDraft(
                id=chunk_id(item.email_id, kind, attachment_id, span.seq),
                email_id=item.email_id,
                attachment_id=attachment_id,
                thread_id=item.thread_id,
                kind=kind,
                seq=span.seq,
                text_for_display=text,
                text_for_index=indexed,
                text_sha256=_sha256(indexed),
                language=language,
                index_version=version,
                source_account_id=item.source_account_id,
                source_account_num=item.source_account_num,
                sent_at=item.sent_at,
                sender_handle=item.sender_handle,
                recipient_handles=item.recipient_handles,
                participant_handles=item.participant_handles,
                direction=item.direction,
                has_attachment=item.has_attachment,
                is_trash_or_spam=item.is_trash_or_spam,
                tags=item.tags,
                meta=meta,
            )
        )

    build = _build_row(
        item, kind, attachment_id, version, built_at, len(drafts), source_digest
    )
    return drafts, build


def _header_only(
    item: ChunkWorkItem,
    kind: ChunkKind,
    prefix: str,
    version: str,
    attachment_id: uuid.UUID | None,
) -> ChunkDraft:
    return ChunkDraft(
        id=chunk_id(item.email_id, kind, attachment_id, 0),
        email_id=item.email_id,
        attachment_id=attachment_id,
        thread_id=item.thread_id,
        kind=kind,
        seq=0,
        text_for_display="",
        text_for_index=prefix,
        text_sha256=_sha256(prefix),
        language=None,
        index_version=version,
        source_account_id=item.source_account_id,
        source_account_num=item.source_account_num,
        sent_at=item.sent_at,
        sender_handle=item.sender_handle,
        recipient_handles=item.recipient_handles,
        participant_handles=item.participant_handles,
        direction=item.direction,
        has_attachment=item.has_attachment,
        is_trash_or_spam=item.is_trash_or_spam,
        tags=item.tags,
        meta={"header_only": True},
    )


def _build_row(
    item: ChunkWorkItem,
    kind: ChunkKind,
    attachment_id: uuid.UUID | None,
    version: str,
    built_at: datetime,
    chunk_count: int,
    source_digest: str | None,
) -> ChunkBuildRow:
    return ChunkBuildRow(
        chunk_kind=kind.value,
        attachment_id=attachment_id,
        index_version=version,
        source_digest=source_digest,
        built_at=built_at,
        chunk_count=chunk_count,
        status=_STATUS_DONE,
        error=None,
    )


def build_email_chunks(
    item: ChunkWorkItem,
    *,
    counter: TokenCounter,
    params: ChunkingParams,
    version: str,
    built_at: datetime,
) -> tuple[list[ChunkDraft], list[ChunkBuildRow]]:
    """Compute all chunk drafts and build rows for one email (pure + tokenizer)."""
    drafts: list[ChunkDraft] = []
    builds: list[ChunkBuildRow] = []

    clean = item.clean_text
    if clean is None:
        return drafts, builds

    prefix_ctx = _prefix_context(item)
    body_prefix = build_prefix(ChunkKind.EMAIL_BODY, prefix_ctx)
    body_text = _body_text(item, params)
    body_segments = [
        seg
        for seg in item.segments
        if seg.kind in _BODY_SEGMENT_KINDS
        or (params.include_signature and seg.kind == "signature")
    ]

    body_drafts, body_build = _chunk_source(
        item=item,
        kind=ChunkKind.EMAIL_BODY,
        source_text=body_text,
        prefix=body_prefix,
        counter=counter,
        params=params,
        version=version,
        built_at=built_at,
        attachment_id=None,
        language=_dominant_language(body_segments, clean),
        meta={},
        source_digest=item.segments_digest,
    )
    drafts.extend(body_drafts)
    builds.append(body_build)

    quote_segments = _quote_segments(item)
    if quote_segments:
        quote_text = "".join(
            clean[seg.start_offset : seg.end_offset] for seg in quote_segments
        )
        quote_text, quote_truncated = truncate_to_tokens(
            quote_text, params.max_quote_tokens_per_email, counter
        )
        quote_prefix = build_prefix(
            ChunkKind.EMAIL_QUOTE,
            replace(prefix_ctx, quoted_author=_first_quoted_author(quote_segments)),
        )
        quote_drafts, quote_build = _chunk_source(
            item=item,
            kind=ChunkKind.EMAIL_QUOTE,
            source_text=quote_text,
            prefix=quote_prefix,
            counter=counter,
            params=params,
            version=version,
            built_at=built_at,
            attachment_id=None,
            language=_dominant_language(quote_segments, clean),
            meta={"truncated": True} if quote_truncated else {},
            source_digest=item.segments_digest,
        )
        drafts.extend(quote_drafts)
        builds.append(quote_build)

    for att in item.attachments:
        if not att.text_ready:
            continue
        att_prefix = build_prefix(
            ChunkKind.ATTACHMENT,
            PrefixContext(
                subject=item.subject,
                sender=item.sender_display,
                recipients=(),
                date=item.sent_at,
                attachment_filename=att.filename,
            ),
        )
        att_meta: dict = {"partial": True} if att.truncated else {}
        att_drafts, att_build = _chunk_source(
            item=item,
            kind=ChunkKind.ATTACHMENT,
            source_text=att.text or "",
            prefix=att_prefix,
            counter=counter,
            params=params,
            version=version,
            built_at=built_at,
            attachment_id=att.attachment_id,
            language=att.language,
            meta=att_meta,
            source_digest=att.source_digest,
        )
        if len(att_drafts) > params.max_chunks_per_attachment:
            att_drafts = att_drafts[: params.max_chunks_per_attachment]
        drafts.extend(att_drafts)
        builds.append(replace(att_build, chunk_count=len(att_drafts)))

    return drafts, builds


def _first_quoted_author(quote_segments) -> str | None:
    for seg in quote_segments:
        if seg.quoted_author:
            return seg.quoted_author
    return None


class EmailChunkingService:
    def __init__(
        self,
        counter: TokenCounter,
        params: ChunkingParams,
        *,
        limit: int = DEFAULT_LIMIT,
    ):
        self._counter = counter
        self._params = params
        self._limit = limit

    @property
    def index_version(self) -> str:
        return index_version(self._counter.version, self._params)

    def chunk(
        self,
        uow: UnitOfWork,
        source_account_id: uuid.UUID,
        *,
        limit: int | None = None,
    ) -> ChunkOutcome:
        version = self.index_version
        stale_ids = uow.chunks.list_stale_email_ids(
            source_account_id=source_account_id,
            index_version=version,
            limit=limit if limit is not None else self._limit,
        )

        counters = {
            "emails_synced": 0,
            "chunks_written": 0,
            "chunks_unchanged": 0,
            "skipped_not_ready": 0,
            "failed": 0,
        }

        # Inputs are read once per batch; built_at is the read time, not the
        # write time.
        built_at = datetime.now(UTC)
        items = uow.chunks.load_chunk_inputs(email_ids=stale_ids)
        for item in items:
            counters["emails_synced"] += 1
            try:
                if item.text_status == _STATUS_FAILED:
                    counters["failed"] += 1
                    continue
                drafts, builds = build_email_chunks(
                    item,
                    counter=self._counter,
                    params=self._params,
                    version=version,
                    built_at=built_at,
                )
                result = uow.chunks.replace_chunks(
                    email_id=item.email_id,
                    drafts=drafts,
                    builds=builds,
                )
                counters["chunks_written"] += result.written
                counters["chunks_unchanged"] += result.unchanged
                counters["skipped_not_ready"] += sum(
                    1 for att in item.attachments if not att.text_ready
                )
            except Exception:  # noqa: BLE001 - per-email failure isolation
                uow.rollback()
                counters["failed"] += 1

            if counters["emails_synced"] % COMMIT_EVERY == 0:
                uow.commit()

        uow.commit()
        return ChunkOutcome(
            emails_synced=counters["emails_synced"],
            chunks_written=counters["chunks_written"],
            chunks_unchanged=counters["chunks_unchanged"],
            skipped_not_ready=counters["skipped_not_ready"],
            failed=counters["failed"],
        )
