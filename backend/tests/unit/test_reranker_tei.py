"""Unit tests for the TEI cross-encoder reranker adapter.

Driven by ``httpx.MockTransport``: the request body (``raw_scores``,
``return_text``), batch splitting and index remapping, response validation, the
one-shot retry on transient failure, and the circuit breaker.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from rosalind.adapters.outbound.search.reranker_tei import CircuitBreaker, TeiReranker
from rosalind.application.search import RerankBackendError, RerankError


def _reranker(
    handler, *, max_batch_size=32, concurrency=1, retries=0, **kwargs
) -> TeiReranker:
    return TeiReranker(
        "http://localhost:8080",
        max_batch_size=max_batch_size,
        concurrency=concurrency,
        retries=retries,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def _run(coro):
    return asyncio.run(coro)


def _ok_by_index(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    texts = body["texts"]
    return httpx.Response(
        200,
        json=[
            {"index": index, "score": float(index + 1)} for index in range(len(texts))
        ],
    )


def test_request_carries_raw_scores_and_return_text() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["body"] = body
        return _ok_by_index(request)

    reranker = _reranker(handler)
    scores = _run(reranker.rerank("query text", ("a", "b")))

    assert scores == (1.0, 2.0)
    assert captured["body"]["raw_scores"] is True
    assert captured["body"]["return_text"] is False
    assert captured["body"]["query"] == "query text"
    assert captured["body"]["texts"] == ["a", "b"]


def test_batches_split_and_merge_by_index() -> None:
    scores_by_text = {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        texts = body["texts"]
        # Return indices in reverse order to prove remapping, not order luck.
        return httpx.Response(
            200,
            json=[
                {"index": index, "score": scores_by_text[text]}
                for index, text in reversed(list(enumerate(texts)))
            ],
        )

    reranker = _reranker(handler, max_batch_size=2)
    scores = _run(reranker.rerank("q", ("a", "b", "c", "d", "e")))

    assert scores == (5.0, 4.0, 3.0, 2.0, 1.0)


def test_duplicate_indices_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[{"index": 0, "score": 1.0}, {"index": 0, "score": 2.0}]
        )

    reranker = _reranker(handler)
    with pytest.raises(RerankError, match="duplicate"):
        _run(reranker.rerank("q", ("a", "b")))


def test_out_of_range_index_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[{"index": 0, "score": 1.0}, {"index": 2, "score": 2.0}]
        )

    reranker = _reranker(handler)
    with pytest.raises(RerankError, match="out-of-range"):
        _run(reranker.rerank("q", ("a", "b")))


def test_length_mismatch_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"index": 0, "score": 1.0}])

    reranker = _reranker(handler)
    with pytest.raises(RerankError, match="expected 2"):
        _run(reranker.rerank("q", ("a", "b")))


def test_non_transient_4xx_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "bad input"})

    reranker = _reranker(handler)
    with pytest.raises(RerankError, match="422"):
        _run(reranker.rerank("q", ("a",)))


def test_retries_on_5xx_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "unavailable"})
        return _ok_by_index(request)

    reranker = _reranker(handler, retries=3)
    assert _run(reranker.rerank("q", ("a", "b"))) == (1.0, 2.0)
    assert calls["n"] == 3


def test_retry_exhaustion_raises_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    reranker = _reranker(handler, retries=1)
    with pytest.raises(RerankBackendError):
        _run(reranker.rerank("q", ("a",)))


def test_circuit_breaker_opens_after_failures() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    reranker = _reranker(handler, breaker_threshold=1, breaker_cooldown_s=60.0)
    with pytest.raises(RerankBackendError):
        _run(reranker.rerank("q", ("a",)))
    with pytest.raises(RerankBackendError, match="circuit breaker"):
        _run(reranker.rerank("q", ("a",)))

    assert calls["n"] == 1  # the second call never reached the server


def test_circuit_breaker_success_resets() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _ok_by_index(request)

    reranker = _reranker(handler, breaker_threshold=2)
    assert _run(reranker.rerank("q", ("a",))) == (1.0,)
    assert _run(reranker.rerank("q", ("a",))) == (1.0,)


def test_breaker_check_raises_when_open() -> None:
    breaker = CircuitBreaker(threshold=1, cooldown_s=60.0)
    breaker.record_failure()
    with pytest.raises(RerankBackendError, match="circuit breaker"):
        breaker.check()


def test_breaker_recovers_after_cooldown() -> None:
    breaker = CircuitBreaker(threshold=1, cooldown_s=0.0)
    breaker.record_failure()
    breaker.check()  # cooldown already expired: half-open trial allowed
    breaker.record_success()
    assert breaker._opened_at is None
