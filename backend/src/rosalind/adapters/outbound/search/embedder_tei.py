"""Text Embeddings Inference (TEI) embedder over HTTP.

A thin ``httpx`` client for a TEI server. The adapter owns HTTP concerns only:
connection reuse, timeouts, retry-on-transient-failure with backoff, and bounded
concurrency (parallel requests, split across ``concurrency`` workers). It maps
the TEI JSON response to plain ``list[float]`` vectors; the application layer
validates them against the configured ``EmbeddingSpace``.

Truncation is off by default: overlong input fails loudly instead of being cut
silently, so a chunk that is too long for the model is quarantined rather than
silently embedded as a truncated prefix.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from rosalind.application.ports.embedding import EmbeddingError, TransientEmbeddingError
from rosalind.domain.search import EmbeddingSpace, Vector

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _locality(url: str) -> str:
    """Classify an embedder URL as local or remote (disclosure surface)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "local"
    return "local" if (parsed.hostname or "") in _LOCAL_HOSTS else "remote"


def _chunk_indices(n: int, k: int) -> list[list[int]]:
    if n == 0:
        return []
    k = max(1, min(k, n))
    size, rem = divmod(n, k)
    out: list[list[int]] = []
    start = 0
    for i in range(k):
        length = size + (1 if i < rem else 0)
        out.append(list(range(start, start + length)))
        start += length
    return out


def _backoff(attempt: int) -> float:
    return min(0.5 * (2 ** (attempt - 1)), 8.0)


def _parse_response(data: object, expected: int) -> list[Vector]:
    if not isinstance(data, list):
        raise EmbeddingError("embedder response is not a list")
    if len(data) != expected:
        raise EmbeddingError(
            f"embedder returned {len(data)} vectors, expected {expected}"
        )
    vectors: list[Vector] = []
    for item in data:
        if not isinstance(item, list) or not all(
            isinstance(value, (int, float)) for value in item
        ):
            raise EmbeddingError("embedder returned a non-vector element")
        vectors.append([float(value) for value in item])
    return vectors


class TeiEmbedder:
    def __init__(
        self,
        url: str,
        space: EmbeddingSpace,
        *,
        timeout: float = 60.0,
        concurrency: int = 2,
        retries: int = 3,
        truncate: bool = False,
        transport: httpx.BaseTransport | None = None,
    ):
        if not url:
            raise ValueError("embedder url must not be empty")
        self._url = url.rstrip("/")
        self._space = space
        self._timeout = timeout
        self._concurrency = max(1, concurrency)
        self._retries = max(0, retries)
        self._truncate = truncate
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            limits=httpx.Limits(
                max_connections=concurrency, max_keepalive_connections=concurrency
            ),
        )

    @property
    def space(self) -> EmbeddingSpace:
        return self._space

    @property
    def locality(self) -> str:
        return _locality(self._url)

    @property
    def host(self) -> str:
        return self._url

    @property
    def device_class(self) -> str:
        # TEI's /info can refine this; keep it fixed for v1.
        return "cpu"

    def embed_documents(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        batches = _chunk_indices(len(texts), self._concurrency)
        with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
            results = list(
                executor.map(
                    lambda idxs: self._request([texts[i] for i in idxs]), batches
                )
            )
        vectors: list[Vector] = []
        for result in results:
            vectors.extend(result)
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"embedder returned {len(vectors)} vectors, expected {len(texts)}"
            )
        return vectors

    def embed_query(self, text: str) -> Vector:
        return self._request([text])[0]

    def _request(self, texts: list[str]) -> list[Vector]:
        attempt = 0
        while True:
            try:
                response = self._client.post(
                    f"{self._url}/embed",
                    json={
                        "inputs": texts,
                        "truncate": self._truncate,
                        "normalize": self._space.normalized,
                    },
                )
                response.raise_for_status()
                return _parse_response(response.json(), len(texts))
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code == 429 or code >= 500:
                    if attempt >= self._retries:
                        raise TransientEmbeddingError(
                            f"embedder returned {code} after {self._retries + 1} attempts"
                        ) from exc
                    attempt += 1
                    time.sleep(_backoff(attempt))
                    continue
                raise EmbeddingError(
                    f"embedder rejected request (HTTP {code})"
                ) from exc
            except httpx.TimeoutException as exc:
                if attempt >= self._retries:
                    raise TransientEmbeddingError("embedder timed out") from exc
                attempt += 1
                time.sleep(_backoff(attempt))
                continue
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    raise TransientEmbeddingError(
                        f"embedder unreachable: {exc}"
                    ) from exc
                attempt += 1
                time.sleep(_backoff(attempt))
                continue

    def close(self) -> None:
        self._client.close()
