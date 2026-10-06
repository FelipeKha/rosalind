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


def space_for(model_id: str, version: str) -> EmbeddingSpace:
    """Resolve the space a plan's ``(embedding_model, embedding_version)`` refers to.

    The plan carries ``embedding_version`` as ``revision or name`` (see
    ``composition._search_config``), so a space matches on ``model_id`` plus
    ``(revision or name)``. Raises ``KeyError`` when no space matches, so a plan
    pointing at an unknown model/version is refused instead of silently querying
    the wrong column.
    """
    for space in _SPACES.values():
        if space.model_id == model_id and (space.revision or space.name) == version:
            return space
    raise KeyError(
        f"no embedding space for model {model_id!r} version {version!r}; "
        f"known spaces: {sorted(_SPACES)}"
    )


def space_columns(name: str) -> SpaceColumns:
    try:
        return _COLUMNS[name]
    except KeyError:
        raise KeyError(
            f"unknown embedding space {name!r}; known spaces: {sorted(_COLUMNS)}"
        ) from None


def known_spaces() -> tuple[str, ...]:
    return tuple(sorted(_SPACES))
