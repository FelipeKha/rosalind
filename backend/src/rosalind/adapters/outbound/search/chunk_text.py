"""Read-only adapter that fetches chunk text for reranking (online search step 4).

Implements ``ChunkTextPort``. One query fetches the selected text column for the
requested chunk ids and restores the caller's order in Python; ids that no
longer exist (a rebuild shrank the chunk count between retrieve and rerank) are
silently absent rather than an error. A database failure is a real retrieval
failure, so it is raised as ``RerankError``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.application.search.rerank import ChunkText, RerankError, RerankTextMode

__all__ = ["PostgresChunkTextRepository"]


class PostgresChunkTextRepository:
    """Fetches rerank text from ``search.chunk`` on a short-lived session."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._factory = session_factory

    async def get_rerank_texts(
        self, chunk_ids: tuple[uuid.UUID, ...], mode: RerankTextMode
    ) -> tuple[ChunkText, ...]:
        try:
            return await asyncio.to_thread(self._get, chunk_ids, mode)
        except SQLAlchemyError as exc:
            raise RerankError("failed to fetch candidate chunk text") from exc

    def _get(
        self, chunk_ids: tuple[uuid.UUID, ...], mode: RerankTextMode
    ) -> tuple[ChunkText, ...]:
        if not chunk_ids:
            return ()
        column = (
            models.Chunk.text_for_index
            if mode is RerankTextMode.INDEX
            else models.Chunk.text_for_display
        )
        with self._factory() as session:
            rows = session.execute(
                select(models.Chunk.id, column).where(models.Chunk.id.in_(chunk_ids))
            ).all()
        by_id = {chunk_id: text for chunk_id, text in rows}
        return tuple(
            ChunkText(chunk_id=chunk_id, text=by_id[chunk_id])
            for chunk_id in chunk_ids
            if chunk_id in by_id
        )
