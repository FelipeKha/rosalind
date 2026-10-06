"""Search-chunk domain: chunk value objects, chunking, and prefix templates."""

from rosalind.domain.search.chunking import chunk_text, truncate_to_tokens
from rosalind.domain.search.chunks import (
    CHUNKER_VERSION,
    PREFIX_VERSION,
    ChunkDraft,
    ChunkingParams,
    ChunkKind,
    ChunkSpan,
    chunk_id,
    index_version,
    params_digest,
)
from rosalind.domain.search.prefix import PrefixContext, build_prefix
from rosalind.domain.search.tokens import TokenCounter

__all__ = [
    "CHUNKER_VERSION",
    "PREFIX_VERSION",
    "ChunkDraft",
    "ChunkKind",
    "ChunkSpan",
    "ChunkingParams",
    "PrefixContext",
    "TokenCounter",
    "build_prefix",
    "chunk_id",
    "chunk_text",
    "index_version",
    "params_digest",
    "truncate_to_tokens",
]
