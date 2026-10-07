import math
from typing import Any

import pytest

from rosalind.application.ports.embedding import EmbeddingError, TransientEmbeddingError
from rosalind.application.services.embedding import (
    EmailEmbeddingService,
    _group_by_text,
    _token_batches,
)
from rosalind.domain.search import (
    ChunkKind,
    EmbeddingSpace,
    embeddable,
    validate_vector,
)

_SPACE = EmbeddingSpace(
    name="bge_m3_v1",
    model_id="BAAI/bge-m3",
    revision="t",
    dtype="float16",
    dimension=4,
    normalized=True,
    column="emb_bge_m3_v1",
)


class _Item:
    def __init__(self, chunk_id, text, sha):
        self.chunk_id = chunk_id
        self.text = text
        self.text_sha256 = sha


class _Counter:
    version = "char/1"

    def count(self, text: str) -> int:
        return len(text)

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        return [0, len(text)]


def _vector(text: str, dim: int = 4) -> list[float]:
    import hashlib
    import random

    rng = random.Random(
        int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    )
    vals = [rng.uniform(-1, 1) for _ in range(dim)]
    norm = math.sqrt(sum(v * v for v in vals))
    return [v / norm for v in vals]


class _FakeEmbedder:
    def __init__(self, space=_SPACE, *, fail=None, transient=False):
        self._space = space
        self._fail = set(fail or ())
        self._transient = transient

    @property
    def space(self):
        return self._space

    @property
    def locality(self):
        return "local"

    @property
    def host(self):
        return "fake"

    @property
    def device_class(self):
        return "cpu"

    def embed_documents(self, texts):
        if self._transient:
            raise TransientEmbeddingError("down")
        out = []
        for text in texts:
            if text in self._fail:
                raise EmbeddingError(f"cannot embed {text!r}")
            out.append(_vector(text, self._space.dimension))
        return out

    def embed_query(self, text):
        return _vector(text, self._space.dimension)


def _service(**kwargs) -> EmailEmbeddingService:
    defaults: dict[str, Any] = {
        "embedder": _FakeEmbedder(),
        "counter": _Counter(),
        "embed_quotes": False,
        "embed_trash_spam": False,
        "allow_remote_embedding": True,
        "window": 100,
        "batch_tokens": 1000,
    }
    defaults.update(kwargs)
    return EmailEmbeddingService(**defaults)


def test_embedding_space_validation() -> None:
    with pytest.raises(ValueError):
        EmbeddingSpace("", "m", "r", "float16", 4, True, "c")
    with pytest.raises(ValueError):
        EmbeddingSpace("s", "m", "r", "float16", 0, True, "c")
    with pytest.raises(ValueError):
        EmbeddingSpace("s", "m", "r", "int8", 4, True, "c")


def test_validate_vector_checks_length_nan_norm() -> None:
    with pytest.raises(ValueError, match="dims"):
        validate_vector([1.0, 0.0, 0.0], _SPACE)
    with pytest.raises(ValueError, match="non-finite"):
        validate_vector([1.0, math.nan, 0.0, 0.0], _SPACE)
    with pytest.raises(ValueError, match="norm"):
        validate_vector([1.0, 1.0, 1.0, 1.0], _SPACE)
    validate_vector([1.0, 0.0, 0.0, 0.0], _SPACE)


def test_embeddable_rule() -> None:
    assert embeddable(
        ChunkKind.EMAIL_BODY, False, embed_quotes=False, embed_trash_spam=False
    )
    assert embeddable(
        ChunkKind.ATTACHMENT, False, embed_quotes=False, embed_trash_spam=False
    )
    assert not embeddable(
        ChunkKind.EMAIL_QUOTE, False, embed_quotes=False, embed_trash_spam=False
    )
    assert embeddable(
        ChunkKind.EMAIL_QUOTE, False, embed_quotes=True, embed_trash_spam=False
    )
    assert not embeddable(
        ChunkKind.EMAIL_BODY, True, embed_quotes=False, embed_trash_spam=False
    )
    assert embeddable(
        ChunkKind.EMAIL_BODY, True, embed_quotes=False, embed_trash_spam=True
    )


def test_group_by_text_dedups_preserving_order() -> None:
    items = [
        _Item("a", "same", "sha1"),
        _Item("b", "same", "sha2"),
        _Item("c", "other", "sha3"),
    ]
    groups = _group_by_text(items)
    assert list(groups) == ["same", "other"]
    assert [i.chunk_id for i in groups["same"]] == ["a", "b"]


def test_token_batches_respect_budget() -> None:
    groups: dict[str, list] = {"hello": [], "world": [], "x": []}  # lengths 5, 5, 1
    batches = _token_batches(groups, _Counter(), batch_tokens=10)
    # "hello"(5) + "world"(5) == 10 fits one batch; "x"(1) would exceed it.
    assert [[t for t, _ in b] for b in batches] == [["hello", "world"], ["x"]]


def test_embed_texts_bisects_non_transient_failure() -> None:
    service = _service(embedder=_FakeEmbedder(fail={"bad"}))
    ok, failures, transient = service._embed_texts(["good1", "bad", "good2"])
    assert set(ok) == {"good1", "good2"}
    assert [text for text, _ in failures] == ["bad"]
    assert transient is None


def test_embed_texts_aborts_on_transient() -> None:
    service = _service(embedder=_FakeEmbedder(transient=True))
    ok, failures, transient = service._embed_texts(["a", "b"])
    assert ok == {}
    assert failures == []
    assert transient is not None
