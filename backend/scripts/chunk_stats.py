"""Chunk statistics report (run before any embedding).

Reads ``search.chunk`` / ``search.chunk_build`` and prints counts per kind, a
text-length histogram, and flags (header-only / truncated / partial) so the
token budget and duplication can be reviewed against real data before phase 6.

Operational tooling: talks to Postgres directly via the configured session.

Usage:
    uv run python -m scripts.chunk_stats
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import text

from rosalind.adapters.outbound.persistence.session import SessionLocal

_HISTOGRAM_EDGES = [0, 64, 128, 256, 512, 1024, 2048, 4096]


def main() -> None:
    with SessionLocal() as session:
        kind_counts: dict[str, int] = dict(
            session.execute(
                text(
                    "SELECT chunk_kind, count(*) FROM search.chunk "
                    "GROUP BY chunk_kind ORDER BY chunk_kind"
                )
            ).all()
        )

        header_only = session.scalar(
            text(
                "SELECT count(*) FROM search.chunk WHERE meta->>'header_only' = 'true'"
            )
        )
        truncated = session.scalar(
            text("SELECT count(*) FROM search.chunk WHERE meta->>'truncated' = 'true'")
        )
        partial = session.scalar(
            text("SELECT count(*) FROM search.chunk WHERE meta->>'partial' = 'true'")
        )

        build_status: dict[str, int] = dict(
            session.execute(
                text(
                    "SELECT status, count(*) FROM search.chunk_build "
                    "GROUP BY status ORDER BY status"
                )
            ).all()
        )

        lengths = [
            length
            for (length,) in session.execute(
                text("SELECT length(text_for_index) FROM search.chunk")
            ).all()
        ]

        attachment_chunks = kind_counts.get("attachment", 0)
        distinct_blobs = session.scalar(
            text("SELECT count(DISTINCT blob_sha256) FROM derived.attachment_text")
        )

    histogram: Counter[int] = Counter()
    for length in lengths:
        bucket = max((edge for edge in _HISTOGRAM_EDGES if length >= edge), default=0)
        histogram[bucket] += 1

    print("Chunk counts per kind:")
    for kind, count in sorted(kind_counts.items()):
        print(f"  {kind}: {count}")

    print("\nBuild status:")
    for status, count in sorted(build_status.items()):
        print(f"  {status}: {count}")

    print("\nFlags:")
    print(f"  header_only: {header_only}")
    print(f"  truncated (quote cap): {truncated}")
    print(f"  partial (attachment truncation): {partial}")

    print("\nText length histogram (characters):")
    for edge in _HISTOGRAM_EDGES:
        print(f"  >= {edge}: {histogram[edge]}")

    if distinct_blobs:
        ratio = attachment_chunks / distinct_blobs
        print(f"\nAttachment duplicate ratio: {ratio:.2f} chunks/blob")
    else:
        print("\nNo attachment blobs extracted.")


if __name__ == "__main__":
    main()
