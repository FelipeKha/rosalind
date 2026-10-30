"""Unit tests for the in-process FlagEmbedding reranker adapter.

Fake-model driven: score passthrough and ordering, pair construction with
``normalize=False``, lazy single load, device resolution, and error mapping to
``RerankBackendError``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from types import SimpleNamespace

import pytest

from rosalind.adapters.outbound.search.reranker_flagembedding import (
    FlagEmbeddingReranker,
)
from rosalind.application.search.rerank import RerankBackendError


class _FakeModel:
    def __init__(self, model_id, **kwargs):
        self.model_id = model_id
        self.init_kwargs = kwargs

    def compute_score(self, sentence_pairs, **kwargs):
        self.last_pairs = sentence_pairs
        self.last_kwargs = kwargs
        return [float(index + 1) for index in range(len(sentence_pairs))]


def _reranker(model_class=_FakeModel, **kwargs) -> FlagEmbeddingReranker:
    kwargs.setdefault("device", "cpu")
    return FlagEmbeddingReranker(
        "BAAI/bge-reranker-v2-m3", model_class=model_class, **kwargs
    )


def _run(coro):
    return asyncio.run(coro)


def test_rerank_returns_scores_in_order() -> None:
    reranker = _reranker()
    assert _run(reranker.rerank("q", ("a", "b", "c"))) == (1.0, 2.0, 3.0)


def test_empty_passages_returns_empty() -> None:
    reranker = _reranker()
    assert _run(reranker.rerank("q", ())) == ()


def test_pairs_built_with_normalize_false() -> None:
    model = _FakeModel("BAAI/bge-reranker-v2-m3")
    reranker = _reranker(model_class=lambda model_id, **kw: model)
    _run(reranker.rerank("what did mike quote", ("passage one", "passage two")))
    assert model.last_pairs == [
        ("what did mike quote", "passage one"),
        ("what did mike quote", "passage two"),
    ]
    assert model.last_kwargs["normalize"] is False


def test_scores_coerced_to_float() -> None:
    class _IntModel:
        def __init__(self, model_id, **kwargs):
            pass

        def compute_score(self, sentence_pairs, **kwargs):
            return [1, 2]

    reranker = _reranker(model_class=_IntModel)
    result = _run(reranker.rerank("q", ("a", "b")))
    assert result == (1.0, 2.0)
    assert all(isinstance(score, float) for score in result)


def test_model_loaded_once() -> None:
    created = []

    def factory(model_id, **kwargs):
        created.append(model_id)
        return _FakeModel(model_id, **kwargs)

    reranker = _reranker(model_class=factory)
    _run(reranker.rerank("q", ("a",)))
    _run(reranker.rerank("q", ("b", "c")))
    assert len(created) == 1


def test_warmup_loads_model_once() -> None:
    created = []

    def factory(model_id, **kwargs):
        created.append(model_id)
        return _FakeModel(model_id, **kwargs)

    reranker = _reranker(model_class=factory)
    reranker.warmup()
    reranker.warmup()

    assert len(created) == 1


def test_invalid_device_raises() -> None:
    with pytest.raises(ValueError, match="unsupported reranker device"):
        FlagEmbeddingReranker("BAAI/bge-reranker-v2-m3", device="cuda")


def test_invalid_model_id_raises() -> None:
    with pytest.raises(ValueError, match="model_id"):
        FlagEmbeddingReranker("", device="cpu")


def test_explicit_device_resolves_without_torch() -> None:
    assert FlagEmbeddingReranker("m", device="mps")._resolve_device() == "mps"
    assert FlagEmbeddingReranker("m", device="cpu")._resolve_device() == "cpu"


def test_auto_device_resolves_mps(monkeypatch) -> None:
    fake_torch = SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True))
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert FlagEmbeddingReranker("m", device="auto")._resolve_device() == "mps"


def test_auto_device_resolves_cpu(monkeypatch) -> None:
    fake_torch = SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert FlagEmbeddingReranker("m", device="auto")._resolve_device() == "cpu"


def test_missing_library_raises_backend_error(monkeypatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    reranker = FlagEmbeddingReranker("BAAI/bge-reranker-v2-m3", device="cpu")
    with pytest.raises(RerankBackendError, match="uv sync --group ml"):
        _run(reranker.rerank("q", ("a",)))


def test_runtime_error_wrapped_as_backend_error() -> None:
    class _BoomModel:
        def __init__(self, model_id, **kwargs):
            pass

        def compute_score(self, sentence_pairs, **kwargs):
            raise RuntimeError("boom")

    reranker = _reranker(model_class=_BoomModel)
    with pytest.raises(RerankBackendError, match="in-process reranker failed"):
        _run(reranker.rerank("q", ("a",)))
