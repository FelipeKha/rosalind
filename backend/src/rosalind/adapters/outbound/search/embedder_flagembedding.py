"""In-process BGE-M3 embedder backed by the FlagEmbedding library.

An ``Embedder`` that loads ``BAAI/bge-m3`` once per process and computes dense
vectors directly, using Apple's MPS backend on Apple Silicon (configurable via
``device``). This is the native local-inference path: no separate serving
container, and the Mac's GPU is used instead of an emulated CPU server.

The model is loaded lazily on first use so wiring the adapter never downloads
weights or imports ``torch``/``FlagEmbedding``. Dense vectors are normalized
here (the space declares ``normalized=True``); the application layer still
re-validates shape/norm against the configured ``EmbeddingSpace``.

Truncation follows FlagEmbedding's default (``truncation=True``): overlong
input is cut by the tokenizer, not rejected. Chunk lengths are bounded to 480
tokens by the chunker, below the 512-token model limit.
"""

from __future__ import annotations

import importlib.util
import math
from typing import Any

from rosalind.application.ports.embedding import EmbeddingError
from rosalind.domain.search import EmbeddingSpace, Vector

_ALLOWED_DEVICES = ("auto", "mps", "cpu")


class FlagEmbeddingEmbedder:
    def __init__(
        self,
        space: EmbeddingSpace,
        *,
        device: str = "auto",
        use_fp16: bool = False,
        batch_size: int = 8,
        max_length: int = 512,
        model_class=None,
    ):
        if device not in _ALLOWED_DEVICES:
            raise ValueError(f"unsupported embedder device {device!r}")
        self._space = space
        self._device = device
        self._use_fp16 = use_fp16
        self._batch_size = max(1, batch_size)
        self._max_length = max(1, max_length)
        self._model_class = model_class
        self._model: Any = None
        self._resolved_device: str | None = None

    @property
    def space(self) -> EmbeddingSpace:
        return self._space

    @property
    def locality(self) -> str:
        return "local"

    @property
    def host(self) -> str:
        return "in-process (FlagEmbedding)"

    @property
    def device_class(self) -> str:
        return self._resolve_device()

    def embed_documents(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        self._ensure_loaded()
        result = self._model.encode(
            texts,
            batch_size=self._batch_size,
            max_length=self._max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return self._dense_to_vectors(result["dense_vecs"], len(texts))

    def embed_query(self, text: str) -> Vector:
        return self.embed_documents([text])[0]

    def _resolve_device(self) -> str:
        if self._resolved_device is None:
            if self._device != "auto":
                self._resolved_device = self._device
            else:
                import torch  # type: ignore[import-not-found]

                self._resolved_device = (
                    "mps" if torch.backends.mps.is_available() else "cpu"
                )
        return self._resolved_device

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        model_class = self._model_class
        if model_class is None:
            if importlib.util.find_spec("FlagEmbedding") is None:
                raise EmbeddingError(
                    "FlagEmbedding is not installed; run `uv sync --group ml` to "
                    "enable in-process embedding"
                )
            import FlagEmbedding  # type: ignore[import-not-found, import-untyped]

            model_class = FlagEmbedding.BGEM3FlagModel
        self._model = model_class(
            self._space.model_id,
            use_fp16=self._use_fp16,
            devices=[self._resolve_device()],
            batch_size=self._batch_size,
            query_max_length=self._max_length,
            passage_max_length=self._max_length,
        )

    def _dense_to_vectors(self, dense, expected: int) -> list[Vector]:
        if dense is None:
            raise EmbeddingError("embedder returned no dense vectors")
        if len(dense) != expected:
            raise EmbeddingError(
                f"embedder returned {len(dense)} vectors, expected {expected}"
            )
        vectors: list[Vector] = []
        for row in dense:
            values = [float(value) for value in row]
            if self._space.normalized:
                norm = math.sqrt(sum(value * value for value in values))
                if norm > 0:
                    values = [value / norm for value in values]
            vectors.append(values)
        return vectors
