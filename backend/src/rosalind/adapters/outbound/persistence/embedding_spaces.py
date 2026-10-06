"""Embedding space registry (adapter concern).

The application layer refers to spaces by their ``EmbeddingSpace`` name; this
module is the single source of truth that resolves a name to both the concrete
domain ``EmbeddingSpace`` (model/dtype/dimension/normalization) and the actual
``search.chunk`` columns that store its vectors. Adding a space means adding a
column pair on ``Chunk``, an entry here, and a migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rosalind.adapters.outbound.persistence import models
from rosalind.domain.search import EmbeddingSpace


@dataclass(frozen=True)
class SpaceColumns:
    """The vector column and its companion text-hash column for one space."""

    vector: Any  # SQLAlchemy column expression (HALFVEC)
    hash_: Any  # SQLAlchemy column expression (Text)


_BGE_M3_V1 = EmbeddingSpace(
    name="bge_m3_v1",
    model_id="BAAI/bge-m3",
    revision="",  # pinned by HF commit hash at deployment time (prereq 0.b)
    dtype="float16",
    dimension=1024,
    normalized=True,
    column="emb_bge_m3_v1",
)

_SPACES: dict[str, EmbeddingSpace] = {_BGE_M3_V1.name: _BGE_M3_V1}

_COLUMNS: dict[str, SpaceColumns] = {
    "bge_m3_v1": SpaceColumns(
        vector=models.Chunk.emb_bge_m3_v1,
        hash_=models.Chunk.emb_bge_m3_v1_text_sha256,
    ),
}


def embedding_space(name: str) -> EmbeddingSpace:
    try:
        return _SPACES[name]
    except KeyError:
        raise KeyError(
            f"unknown embedding space {name!r}; known spaces: {sorted(_SPACES)}"
        ) from None


def space_columns(name: str) -> SpaceColumns:
    try:
        return _COLUMNS[name]
    except KeyError:
        raise KeyError(
            f"unknown embedding space {name!r}; known spaces: {sorted(_COLUMNS)}"
        ) from None


def known_spaces() -> tuple[str, ...]:
    return tuple(sorted(_SPACES))
