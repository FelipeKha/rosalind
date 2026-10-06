"""Query-embedding adapter for the online search Prepare step.

Wraps the offline ``Embedder`` (a TEI server today) behind the async
``EmbedderPort`` used by Prepare. ``embed`` runs in a worker thread and builds
a ``QueryVector`` whose ``digest`` is a hash of the values, so the raw vector is
never logged or echoed.
"""

from __future__ import annotations

import asyncio

from rosalind.application.ports.embedding import Embedder
from rosalind.application.search import QueryVector, vector_digest

__all__ = ["NullEmbedder", "QueryEmbedder"]


class NullEmbedder:
    """An embedder that is never called (no embedding service configured)."""

    async def embed(self, text: str, model: str, version: str) -> QueryVector:
        raise RuntimeError("no embedding service is configured")


class QueryEmbedder:
    def __init__(self, embedder: Embedder):
        self._embedder = embedder

    async def embed(self, text: str, model: str, version: str) -> QueryVector:
        vector = await asyncio.to_thread(self._embedder.embed_query, text)
        values = tuple(vector)
        return QueryVector(
            values=values,
            model=model,
            model_version=version,
            digest=vector_digest(values),
        )
