"""In-process BGE cross-encoder reranker backed by the FlagEmbedding library.

An ``RerankerPort`` that loads ``BAAI/bge-reranker-v2-m3`` once per process and
scores ``(query, passage)`` pairs directly, using Apple's MPS backend on Apple
Silicon (configurable via ``device``). This is the native local-inference path,
matching the embedding adapter: no separate serving container.

The model is loaded lazily on first use so wiring never downloads weights or
imports ``torch``/``FlagEmbedding``. Scores are the model's raw logits
(``normalize=False``), which is what the TEI adapter's ``raw_scores`` flag
produced, so the application's "higher is better" ordering is unchanged.

``compute_score`` is synchronous; ``rerank`` runs it in a worker thread via
``asyncio.to_thread`` to keep the event loop free. Any runtime failure raises
``RerankBackendError`` so the orchestrator degrades to the fused order with a
``RERANK_SKIPPED`` warning rather than failing the search.
"""

from __future__ import annotations

import asyncio
import importlib.util
from typing import Any

from rosalind.application.search.rerank import RerankBackendError

_ALLOWED_DEVICES = ("auto", "mps", "cpu")


class FlagEmbeddingReranker:
    def __init__(
        self,
        model_id: str,
        *,
        device: str = "auto",
        use_fp16: bool = False,
        batch_size: int = 32,
        max_length: int = 512,
        model_class=None,
    ):
        if not model_id:
            raise ValueError("model_id must not be empty")
        if device not in _ALLOWED_DEVICES:
            raise ValueError(f"unsupported reranker device {device!r}")
        self._model_id = model_id
        self._device = device
        self._use_fp16 = use_fp16
        self._batch_size = max(1, batch_size)
        self._max_length = max(1, max_length)
        self._model_class = model_class
        self._model: Any = None
        self._resolved_device: str | None = None

    async def rerank(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        if not passages:
            return ()
        self._ensure_loaded()
        pairs = [(query, passage) for passage in passages]
        try:
            scores = await asyncio.to_thread(
                self._model.compute_score, pairs, normalize=False
            )
        except Exception as exc:
            raise RerankBackendError(f"in-process reranker failed: {exc}") from exc
        return tuple(float(score) for score in scores)

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
                raise RerankBackendError(
                    "FlagEmbedding is not installed; run `uv sync --group ml` to "
                    "enable in-process reranking"
                )
            import FlagEmbedding  # type: ignore[import-not-found, import-untyped]

            model_class = FlagEmbedding.FlagReranker
        self._model = model_class(
            self._model_id,
            use_fp16=self._use_fp16,
            devices=[self._resolve_device()],
            batch_size=self._batch_size,
            max_length=self._max_length,
        )
