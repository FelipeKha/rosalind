"""Lifecycle tests for the full stack: idempotent rerun.

Runs the pipeline a second time and asserts no duplicate canonical records, no
unnecessary chunk rebuilds, stable chunk text, and no redundant embedding work.
"""

from __future__ import annotations

import pytest

from support import db

pytestmark = pytest.mark.rag


def _count(conn, sql, params=None) -> int:
    return db.query_one(conn, sql, params)[0]


def test_rerun_is_idempotent(rag_corpus, rag_run_rosalind) -> None:
    conn = rag_corpus.conn
    import_id = rag_corpus.import_id

    before = {
        "emails": _count(conn, "SELECT count(*) FROM core.email_message"),
        "chunks": _count(conn, "SELECT count(*) FROM search.chunk"),
        "records": _count(
            conn,
            "SELECT count(*) FROM raw.source_record WHERE import_id = %s::uuid",
            (import_id,),
        ),
        "chunk_text": dict(
            db.query_all(conn, "SELECT id::text, text_sha256 FROM search.chunk")
        ),
    }

    result = rag_run_rosalind(["index", import_id])
    assert result.returncode == 0, result.stderr

    assert _count(conn, "SELECT count(*) FROM core.email_message") == before["emails"]
    assert _count(conn, "SELECT count(*) FROM search.chunk") == before["chunks"]
    assert (
        _count(
            conn,
            "SELECT count(*) FROM raw.source_record WHERE import_id = %s::uuid",
            (import_id,),
        )
        == before["records"]
    )

    after_text = dict(
        db.query_all(conn, "SELECT id::text, text_sha256 FROM search.chunk")
    )
    assert after_text == before["chunk_text"]

    # The rerun performed no new embedding work.
    latest = db.query_one(
        conn,
        "SELECT chunks_embedded, chunks_failed FROM search.embedding_run "
        "ORDER BY started_at DESC, finished_at DESC LIMIT 1",
    )
    assert latest == (0, 0)
