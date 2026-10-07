import json

import httpx
import pytest

from rosalind.adapters.outbound.search.embedder_tei import TeiEmbedder
from rosalind.application.ports.embedding import EmbeddingError, TransientEmbeddingError
from rosalind.domain.search import EmbeddingSpace

_SPACE = EmbeddingSpace(
    name="bge_m3_v1",
    model_id="BAAI/bge-m3",
    revision="t",
    dtype="float16",
    dimension=2,
    normalized=True,
    column="emb_bge_m3_v1",
)


def _embedder(handler, *, concurrency=1, retries=0) -> TeiEmbedder:
    transport = httpx.MockTransport(handler)
    return TeiEmbedder(
        "http://localhost:8080",
        _SPACE,
        concurrency=concurrency,
        retries=retries,
        transport=transport,
    )


def _ok(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    inputs = body["inputs"]
    return httpx.Response(200, json=[[0.5, 0.5] for _ in inputs])


def test_embed_documents_round_trips() -> None:
    embedder = _embedder(_ok)
    vectors = embedder.embed_documents(["a", "b", "c"])
    assert len(vectors) == 3
    assert all(v == [0.5, 0.5] for v in vectors)


def test_embed_query_returns_single_vector() -> None:
    embedder = _embedder(_ok)
    assert embedder.embed_query("q") == [0.5, 0.5]


def test_length_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[0.5, 0.5]])  # one vector for two inputs

    embedder = _embedder(handler)
    with pytest.raises(EmbeddingError, match="returned 1 vectors, expected 2"):
        embedder.embed_documents(["a", "b"])


def test_non_transient_4xx_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "bad input"})

    embedder = _embedder(handler)
    with pytest.raises(EmbeddingError, match="422"):
        embedder.embed_documents(["a"])


def test_retries_on_5xx_then_raises_transient(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    monkeypatch.setattr(
        "rosalind.adapters.outbound.search.embedder_tei.time.sleep", lambda _: None
    )
    embedder = _embedder(handler, retries=2)
    with pytest.raises(TransientEmbeddingError):
        embedder.embed_documents(["a"])
    assert calls["n"] == 3  # initial + 2 retries


def test_retries_then_succeeds(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": "slow down"})
        return _ok(request)

    monkeypatch.setattr(
        "rosalind.adapters.outbound.search.embedder_tei.time.sleep", lambda _: None
    )
    embedder = _embedder(handler, retries=3)
    assert embedder.embed_documents(["a"]) == [[0.5, 0.5]]
    assert calls["n"] == 3


def test_truncate_and_normalize_params_sent() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _ok(request)

    embedder = _embedder(handler)
    embedder.embed_documents(["a"])
    assert captured["body"]["truncate"] is False
    assert captured["body"]["normalize"] is True
