"""Persistence for embeddings (``search.chunk`` columns, failure/run tables).

The only module that talks SQL for the embedding write path. ``find_embed_work``
is the work finder: chunks of embeddable kinds whose vector is missing or whose
companion hash no longer matches ``text_sha256``. ``write_embeddings`` applies a
guarded bulk update — a vector is written only if the chunk's ``text_sha256``
still equals the one that was embedded — so edits landing mid-run can't be
overwritten.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import (
    Text,
    Uuid,
    cast,
    column,
    delete,
    func,
    or_,
    select,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.embedding_spaces import space_columns
from rosalind.application.ports.embedding import (
    EmbeddingFailureRow,
    EmbeddingRunRow,
    EmbedWorkItem,
    EmbedWrite,
)
from rosalind.domain.search import EmbeddingSpace


def _embeddable_preds(
    c: type[models.Chunk], *, embed_quotes: bool, embed_trash_spam: bool
) -> list:
    """SQL mirror of ``domain.search.embedding.embeddable`` for the chunk table."""
    preds = []
    if not embed_quotes:
        preds.append(c.chunk_kind != "email_quote")
    if not embed_trash_spam:
        preds.append(c.is_trash_or_spam.is_(False))
    return preds


class PostgresEmbeddingRepository:
    def __init__(self, session: Session):
        self._session = session

    def find_embed_work(
        self,
        *,
        space: EmbeddingSpace,
        source_account_id: uuid.UUID,
        embed_quotes: bool,
        embed_trash_spam: bool,
        retry_failed: bool,
        limit: int,
    ) -> list[EmbedWorkItem]:
        c = models.Chunk
        f = models.EmbeddingFailure
        cols = space_columns(space.name)

        needs_embed = or_(
            cols.vector.is_(None),
            cols.hash_.is_distinct_from(c.text_sha256),
        )

        stmt = (
            select(c.id, c.text_for_index, c.text_sha256)
            .where(
                c.source_account_id == source_account_id,
                *_embeddable_preds(
                    c, embed_quotes=embed_quotes, embed_trash_spam=embed_trash_spam
                ),
                needs_embed,
            )
            .order_by(c.sent_at.desc(), c.id)
            .limit(limit)
        )

        if not retry_failed:
            stmt = stmt.where(
                ~(
                    select(1)
                    .where(
                        f.chunk_id == c.id,
                        f.space == space.name,
                        f.text_sha256 == c.text_sha256,
                    )
                    .exists()
                )
            )

        rows = self._session.execute(stmt).all()
        return [
            EmbedWorkItem(chunk_id=row[0], text=row[1], text_sha256=row[2])
            for row in rows
        ]

    def count_not_embeddable(
        self,
        *,
        source_account_id: uuid.UUID,
        embed_quotes: bool,
        embed_trash_spam: bool,
    ) -> int:
        c = models.Chunk
        preds: list = []
        if not embed_quotes:
            preds.append(c.chunk_kind == "email_quote")
        if not embed_trash_spam:
            preds.append(c.is_trash_or_spam.is_(True))
        if not preds:
            return 0
        stmt = select(func.count()).where(
            c.source_account_id == source_account_id, or_(*preds)
        )
        return int(self._session.scalar(stmt) or 0)

    def write_embeddings(
        self, *, space: EmbeddingSpace, writes: Sequence[EmbedWrite]
    ) -> list[uuid.UUID]:
        if not writes:
            return []

        c = models.Chunk
        cols = space_columns(space.name)

        v = values(
            column("id", Uuid),
            column("vec", cols.vector.type),
            column("sha", Text),
            name="embed_writes",
        ).data([(w.chunk_id, w.vector, w.expected_text_sha256) for w in writes])

        stmt = (
            update(c)
            .where(
                c.id == v.c.id,
                c.text_sha256 == v.c.sha,
            )
            .values(
                {
                    cols.vector: cast(v.c.vec, cols.vector.type),
                    cols.hash_: v.c.sha,
                }
            )
            .returning(c.id)
        )
        written = [row[0] for row in self._session.execute(stmt).all()]

        if written:
            self._session.execute(
                delete(models.EmbeddingFailure).where(
                    models.EmbeddingFailure.chunk_id.in_(written),
                    models.EmbeddingFailure.space == space.name,
                )
            )
        return written

    def record_failure(self, *, row: EmbeddingFailureRow) -> None:
        stmt = (
            pg_insert(models.EmbeddingFailure)
            .values(
                chunk_id=row.chunk_id,
                space=row.space,
                text_sha256=row.text_sha256,
                error=row.error,
                attempts=row.attempts,
                last_attempt_at=row.last_attempt_at,
            )
            .on_conflict_do_update(
                index_elements=["chunk_id", "space"],
                set_={
                    "text_sha256": row.text_sha256,
                    "error": row.error,
                    "attempts": models.EmbeddingFailure.attempts + 1,
                    "last_attempt_at": row.last_attempt_at,
                },
            )
        )
        self._session.execute(stmt)

    def record_run(self, *, row: EmbeddingRunRow) -> None:
        self._session.add(
            models.EmbeddingRun(
                space=row.space,
                started_at=row.started_at,
                finished_at=row.finished_at,
                host=row.host,
                device_class=row.device_class,
                dtype=row.dtype,
                revision=row.revision,
                locality=row.locality,
                chunks_embedded=row.chunks_embedded,
                chunks_failed=row.chunks_failed,
            )
        )
