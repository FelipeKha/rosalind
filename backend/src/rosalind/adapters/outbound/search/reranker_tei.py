"""Text Embeddings Inference (TEI) cross-encoder reranker over HTTP.

A thin ``httpx.AsyncClient`` adapter for a TEI server's ``/rerank`` endpoint.
The adapter owns HTTP concerns only: connection reuse, per-request timeouts,
one-shot retries on transient failure, bounded concurrency, and a small circuit
breaker so a downed reranker is skipped quickly instead of every search burning
its deadline. It sends ``raw_scores: true`` so the application sorts on the raw
model score rather than TEI's default sigmoid-normalized value (which saturates
near 1.0 and creates ties).

The TEI ``/rerank`` response is a list of ``{"index": i, "score": s}`` objects
that may arrive in any order; this adapter validates that the indices are unique
and cover the request, then maps scores back to input order before returning.
"""

from __future__ import annotations

import asyncio
import time
from typing import cast

import httpx

from rosalind.application.search.rerank import RerankBackendError, RerankError

__all__ = ["CircuitBreaker", "TeiReranker"]


def _backoff(attempt: int) -> float:
    return min(0.25 * (2 ** (attempt - 1)), 2.0)


class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures, cooling down before a
    half-open trial is allowed through again."""

    def __init__(self, threshold: int, cooldown_s: float) -> None:
        self._threshold = max(1, threshold)
        self._cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at: float | None = None

    def check(self) -> None:
        if self._opened_at is None:
            return
        if time.monotonic() - self._opened_at < self._cooldown_s:
            raise RerankBackendError("reranker circuit breaker is open")

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = time.monotonic()


def _batches(
    passages: tuple[str, ...], max_batch_size: int
) -> list[list[tuple[int, str]]]:
    """Split passages into batches of ``(global_index, text)`` pairs."""
    out: list[list[tuple[int, str]]] = []
    for start in range(0, len(passages), max_batch_size):
        end = min(start + max_batch_size, len(passages))
        out.append([(index, passages[index]) for index in range(start, end)])
    return out


def _parse_scores(data: object, expected: int) -> list[tuple[int, float]]:
    """Validate a TEI ``/rerank`` response and return ``(index, score)`` pairs.

    Indices must be unique ints covering ``0..expected-1``; the order is not
    assumed to be sorted.
    """
    if not isinstance(data, list):
        raise RerankError("reranker response is not a list")
    if len(data) != expected:
        raise RerankError(f"reranker returned {len(data)} scores, expected {expected}")
    seen: set[int] = set()
    pairs: list[tuple[int, float]] = []
    for item in data:
        if not isinstance(item, dict):
            raise RerankError("reranker returned a non-object element")
        index = item.get("index")
        score = item.get("score")
        if not isinstance(index, int) or not isinstance(score, (int, float)):
            raise RerankError("reranker returned an element missing index/score")
        if index < 0 or index >= expected:
            raise RerankError("reranker returned an out-of-range index")
        if index in seen:
            raise RerankError("reranker returned duplicate indices")
        seen.add(index)
        pairs.append((index, float(score)))
    return pairs


class TeiReranker:
    def __init__(
        self,
        url: str,
        *,
        timeout_s: float = 20.0,
        max_batch_size: int = 32,
        concurrency: int = 1,
        retries: int = 1,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not url:
            raise ValueError("reranker url must not be empty")
        self._url = url.rstrip("/")
        self._max_batch_size = max(1, max_batch_size)
        self._concurrency = max(1, concurrency)
        self._retries = max(0, retries)
        self._breaker = CircuitBreaker(breaker_threshold, breaker_cooldown_s)
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            transport=transport,
            limits=httpx.Limits(
                max_connections=concurrency,
                max_keepalive_connections=concurrency,
            ),
        )

    async def rerank(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        n = len(passages)
        if n == 0:
            return ()

        self._breaker.check()

        batches = _batches(passages, self._max_batch_size)
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run(batch: list[tuple[int, str]]) -> list[tuple[int, float]]:
            async with semaphore:
                return await self._run_batch(query, batch)

        try:
            results = await asyncio.gather(*(run(batch) for batch in batches))
        except RerankBackendError:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()

        scores: list[float | None] = [None] * n
        for pairs in results:
            for global_index, score in pairs:
                if scores[global_index] is not None:
                    raise RerankError("reranker returned duplicate indices")
                scores[global_index] = score
        if any(score is None for score in scores):
            raise RerankError("reranker returned scores for a subset of passages")
        return tuple(cast(float, score) for score in scores)

    async def _run_batch(
        self, query: str, batch: list[tuple[int, str]]
    ) -> list[tuple[int, float]]:
        texts = [text for _, text in batch]
        attempt = 0
        while True:
            try:
                response = await self._client.post(
                    f"{self._url}/rerank",
                    json={
                        "query": query,
                        "texts": texts,
                        "raw_scores": True,
                        "return_text": False,
                    },
                )
                response.raise_for_status()
                parsed = _parse_scores(response.json(), len(texts))
                return [(batch[local][0], score) for local, score in parsed]
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code == 429 or code >= 500:
                    if attempt >= self._retries:
                        raise RerankBackendError(
                            f"reranker returned {code} after {self._retries + 1} attempts"
                        ) from exc
                    attempt += 1
                    await asyncio.sleep(_backoff(attempt))
                    continue
                raise RerankError(f"reranker rejected request (HTTP {code})") from exc
            except httpx.TimeoutException as exc:
                if attempt >= self._retries:
                    raise RerankBackendError("reranker timed out") from exc
                attempt += 1
                await asyncio.sleep(_backoff(attempt))
                continue
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    raise RerankBackendError(f"reranker unreachable: {exc}") from exc
                attempt += 1
                await asyncio.sleep(_backoff(attempt))
                continue

    async def aclose(self) -> None:
        await self._client.aclose()
