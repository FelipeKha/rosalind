import importlib.util
import sys
from types import SimpleNamespace

import pytest

from rosalind.adapters.outbound.search.embedder_flagembedding import (
    FlagEmbeddingEmbedder,
)
from rosalind.application.ports.embedding import EmbeddingError
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


class _FakeModel:
    def __init__(self, model_id, **kwargs):
        self.model_id = model_id
        self.init_kwargs = kwargs
        self.calls = 0

    def encode(self, sentences, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return {"dense_vecs": [[1.0, 0.0] for _ in sentences]}


def _embedder(model_class=_FakeModel, **kwargs) -> FlagEmbeddingEmbedder:
    kwargs.setdefault("device", "cpu")
    return FlagEmbeddingEmbedder(_SPACE, model_class=model_class, **kwargs)


def test_embed_documents_round_trips() -> None:
    embedder = _embedder()
    vectors = embedder.embed_documents(["a", "b", "c"])
    assert len(vectors) == 3
    assert all(v == [1.0, 0.0] for v in vectors)


def test_embed_query_returns_single_vector() -> None:
    embedder = _embedder()
    assert embedder.embed_query("q") == [1.0, 0.0]


def test_empty_batch_returns_empty() -> None:
    assert _embedder().embed_documents([]) == []


def test_length_mismatch_raises() -> None:
    class _ShortModel:
        def __init__(self, model_id, **kwargs):
            pass

        def encode(self, sentences, **kwargs):
            return {"dense_vecs": [[0.5, 0.5]]}  # one vector for two inputs

    embedder = _embedder(model_class=_ShortModel)
    with pytest.raises(EmbeddingError, match="returned 1 vectors, expected 2"):
        embedder.embed_documents(["a", "b"])


def test_missing_dense_raises() -> None:
    class _EmptyModel:
        def __init__(self, model_id, **kwargs):
            pass

        def encode(self, sentences, **kwargs):
            return {"dense_vecs": None}

    embedder = _embedder(model_class=_EmptyModel)
    with pytest.raises(EmbeddingError, match="no dense vectors"):
        embedder.embed_documents(["a"])


def test_dense_vectors_normalized() -> None:
    class _UnnormalizedModel:
        def __init__(self, model_id, **kwargs):
            pass

        def encode(self, sentences, **kwargs):
            return {"dense_vecs": [[3.0, 4.0] for _ in sentences]}

    embedder = _embedder(model_class=_UnnormalizedModel)
    vectors = embedder.embed_documents(["a"])
    assert vectors == [[0.6, 0.8]]


def test_encode_args_passed_through() -> None:
    model = _FakeModel("BAAI/bge-m3")
    embedder = _embedder(
        model_class=lambda model_id, **kw: model, batch_size=4, max_length=64
    )
    embedder.embed_documents(["a"])
    assert model.last_kwargs["batch_size"] == 4
    assert model.last_kwargs["max_length"] == 64
    assert model.last_kwargs["return_dense"] is True
    assert model.last_kwargs["return_sparse"] is False
    assert model.last_kwargs["return_colbert_vecs"] is False


def test_model_loaded_once() -> None:
    created = []

    def factory(model_id, **kwargs):
        created.append(model_id)
        return _FakeModel(model_id, **kwargs)

    embedder = _embedder(model_class=factory)
    embedder.embed_documents(["a"])
    embedder.embed_documents(["b"])
    assert len(created) == 1


def test_warmup_loads_model_once_without_encoding() -> None:
    created = []

    def factory(model_id, **kwargs):
        created.append(model_id)
        return _FakeModel(model_id, **kwargs)

    embedder = _embedder(model_class=factory)
    embedder.warmup()
    embedder.warmup()

    assert len(created) == 1


def test_invalid_device_raises() -> None:
    with pytest.raises(ValueError, match="unsupported embedder device"):
        FlagEmbeddingEmbedder(_SPACE, device="cuda")


def test_explicit_device_class_no_torch_import() -> None:
    assert _embedder(device="mps").device_class == "mps"
    assert _embedder(device="cpu").device_class == "cpu"


def test_auto_device_resolves_mps(monkeypatch) -> None:
    fake_torch = SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True))
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert _embedder(device="auto").device_class == "mps"


def test_auto_device_resolves_cpu(monkeypatch) -> None:
    fake_torch = SimpleNamespace(
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert _embedder(device="auto").device_class == "cpu"


def test_missing_library_raises(monkeypatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    embedder = FlagEmbeddingEmbedder(_SPACE, device="cpu")
    with pytest.raises(EmbeddingError, match="uv sync --group ml"):
        embedder.embed_documents(["a"])


def test_properties() -> None:
    embedder = _embedder(device="cpu")
    assert embedder.locality == "local"
    assert embedder.host == "in-process (FlagEmbedding)"
    assert embedder.space is _SPACE
