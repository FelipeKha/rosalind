"""Semantic retrieval benchmark: exact scan vs HNSW (operational tooling).

Answers the questions that set the semantic retrieval defaults:

* exact-scan latency at the current corpus size;
* HNSW recall@k against the exact top-k;
* p50/p95 latency for both paths.

Run it against a database with backfilled embeddings, *after* creating the HNSW
index (migration 0019). Its output is the input to ``search_semantic_exact_threshold``
and the ``search_hnsw_*`` settings in ``config.py``.

Usage:
    uv run python -m scripts.bench_semantic_retrieval --queries 100 --k 20
"""

from __future__ import annotations

import argparse
import statistics
import time

from sqlalchemy import text

from rosalind.adapters.outbound.persistence.embedding_spaces import (
    embedding_space,
    space_columns,
)
from rosalind.adapters.outbound.persistence.session import SessionLocal
from rosalind.config import settings


def _fmt(vector: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vector) + "]"


def _exact_query(col: str, k: int) -> str:
    return (
        f"WITH filtered AS MATERIALIZED (SELECT id, {col} AS emb FROM search.chunk "  # nosec B608 - fixed registry column
        f"WHERE {col} IS NOT NULL) "
        f"SELECT id FROM filtered ORDER BY emb <=> :q::halfvec, id LIMIT {k}"
    )


def _ann_query(col: str, k: int) -> str:
    return (
        f"SELECT id FROM search.chunk WHERE {col} IS NOT NULL "  # nosec B608 - fixed registry column
        f"ORDER BY {col} <=> :q::halfvec LIMIT {k}"
    )


def _sample_queries(col: str, limit: int) -> list[list[float]]:
    with SessionLocal() as session:
        rows = session.execute(
            text(
                f"SELECT {col} FROM search.chunk WHERE {col} IS NOT NULL LIMIT {limit}"  # nosec B608 - fixed registry column
            )
        ).all()
    return [list(row[0]) for row in rows]


def _run(session, sql: str, query: list[float]) -> tuple[float, set[str]]:
    started = time.perf_counter()
    rows = session.execute(text(sql), {"q": _fmt(query)}).all()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return elapsed_ms, {str(row[0]) for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--k", type=int, default=20)
    args = parser.parse_args()

    space = embedding_space(settings.embedding_space)
    col = space_columns(space.name).vector
    column = str(col.name)

    queries = _sample_queries(column, args.queries)
    if not queries:
        raise SystemExit("no embedded chunks found; run the embed stage first")

    exact_ms: list[float] = []
    ann_ms: list[float] = []
    recalls: list[float] = []

    with SessionLocal() as session:
        session.execute(text("SET hnsw.iterative_scan = 'strict_order'"))
        for query in queries:
            exact, exact_ids = _run(session, _exact_query(column, args.k), query)
            ann, ann_ids = _run(session, _ann_query(column, args.k), query)
            exact_ms.append(exact)
            ann_ms.append(ann)
            recalls.append(len(exact_ids & ann_ids) / len(exact_ids))

    def pct(values: list[float], p: float) -> float:
        return statistics.quantiles(values, n=100, method="inclusive")[int(p * 100) - 1]

    print(f"corpus queries: {len(queries)}, k={args.k}")
    print("\nLatency (ms):")
    print(f"  exact  p50={pct(exact_ms, 0.5):.2f}  p95={pct(exact_ms, 0.95):.2f}")
    print(f"  hnsw   p50={pct(ann_ms, 0.5):.2f}  p95={pct(ann_ms, 0.95):.2f}")
    print("\nRecall@k vs exact:")
    print(f"  mean={statistics.mean(recalls):.3f}  min={min(recalls):.3f}")

    mean_exact = statistics.mean(exact_ms)
    mean_ann = statistics.mean(ann_ms)
    print("\nSuggested settings:")
    if mean_exact < mean_ann:
        print(
            "  exact scan is faster at this corpus size; keep the HNSW index out of "
            "the hot path (low search_semantic_exact_threshold)."
        )
    else:
        print("  hnsw wins; keep the ann_iterative path as default.")


if __name__ == "__main__":
    main()
