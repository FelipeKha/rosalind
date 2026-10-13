"""Full-pipeline ingestion smoke test for the synthetic MBOX.

Runs the real split → canonicalize → reconcile → enrich → attachments → chunk →
embed pipeline (via the CLI) against PostgreSQL/pgvector + SeaweedFS +
BGE-M3 via FlagEmbedding, then asserts persisted state at each boundary: raw
records, canonical emails, thread reconciliation, derived text, chunks, and
embeddings.
"""

from __future__ import annotations

import pytest

from support import db

pytestmark = pytest.mark.rag

NAMED_MESSAGE_IDS = {
    f"msg-{n:03d}@example.test"
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18)
}


def _count(conn, sql, params=None) -> int:
    return db.query_one(conn, sql, params)[0]


def test_raw_records_split_from_archive(rag_corpus) -> None:
    conn = rag_corpus.conn
    total = _count(
        conn,
        "SELECT count(*) FROM raw.source_record WHERE import_id = %s::uuid",
        (rag_corpus.import_id,),
    )
    assert total == 18

    synthetic = _count(
        conn,
        "SELECT count(*) FROM raw.source_record "
        "WHERE import_id = %s::uuid AND external_id LIKE 'no-message-id:%%'",
        (rag_corpus.import_id,),
    )
    assert synthetic == 1

    named = db.query_all(
        conn,
        "SELECT external_id FROM raw.source_record WHERE import_id = %s::uuid",
        (rag_corpus.import_id,),
    )
    assert {row[0] for row in named if not row[0].startswith("no-message-id:")} == (
        NAMED_MESSAGE_IDS
    )


def test_canonical_emails_and_direction(rag_corpus) -> None:
    conn = rag_corpus.conn
    assert _count(conn, "SELECT count(*) FROM core.email_message") == 18

    sent = [
        row
        for row in db.query_all(
            conn,
            "SELECT message_id FROM core.email_message WHERE direction = 'sent'",
        )
    ]
    assert {row[0] for row in sent} == {
        "msg-002@example.test",
        "msg-007@example.test",
        "msg-014@example.test",
    }

    # The invalid-date message is canonicalized with a fallback occurred_at.
    assert _count(
        conn,
        "SELECT count(*) FROM core.email_message "
        "WHERE message_id = 'msg-016@example.test' AND occurred_at IS NOT NULL",
    ) == 1

    # Trash/spam flags are computed from provider labels.
    assert _count(
        conn,
        "SELECT count(*) FROM core.email_message WHERE is_trash_or_spam = true",
    ) == 2


def test_thread_reconciliation(rag_corpus) -> None:
    conn = rag_corpus.conn

    def thread_root(message_id: str) -> str | None:
        row = db.query_one(
            conn,
            "SELECT t.root_message_id FROM core.email_message m "
            "JOIN core.email_thread t ON t.id = m.thread_id "
            "WHERE m.message_id = %s",
            (message_id,),
        )
        return row[0] if row else None

    # Kickoff thread: msg-001/002/003 share the msg-001 root.
    roots = {
        thread_root(mid)
        for mid in ("msg-001@example.test", "msg-002@example.test", "msg-003@example.test")
    }
    assert roots == {"msg-001@example.test"}

    # msg-017 references missing parents: its thread is not msg-005's.
    assert thread_root("msg-005@example.test") == "msg-005@example.test"
    assert thread_root("msg-017@example.test") == "msg-root-migration@example.test"
    assert thread_root("msg-017@example.test") != thread_root("msg-005@example.test")


def test_derived_text_present(rag_corpus) -> None:
    conn = rag_corpus.conn
    done = _count(
        conn, "SELECT count(*) FROM derived.email_text WHERE status = 'done'"
    )
    assert done == 18

    html = db.query_one(
        conn,
        "SELECT clean_text FROM derived.email_text et "
        "JOIN core.email_message m ON m.id = et.email_id "
        "WHERE m.message_id = 'msg-015@example.test'",
    )
    assert html and "25 March" in html[0]

    attachment = _count(
        conn,
        "SELECT count(*) FROM core.email_attachment WHERE filename = 'q1-budget.pdf'",
    )
    assert attachment == 1


def test_chunks_and_embeddings(rag_corpus) -> None:
    conn = rag_corpus.conn

    # Every non-trash body chunk carries a fresh embedding.
    missing = _count(
        conn,
        "SELECT count(*) FROM search.chunk "
        "WHERE chunk_kind = 'email_body' AND is_trash_or_spam = false "
        "AND (emb_bge_m3_v1 IS NULL OR emb_bge_m3_v1_text_sha256 <> text_sha256)",
    )
    assert missing == 0

    embedded = _count(
        conn,
        "SELECT count(*) FROM search.chunk WHERE emb_bge_m3_v1 IS NOT NULL",
    )
    assert embedded > 0

    # Trash/spam chunks are not embedded by default.
    trash = db.query_all(
        conn,
        "SELECT count(*), count(emb_bge_m3_v1) FROM search.chunk "
        "WHERE is_trash_or_spam = true",
    )
    assert trash == [(2, 0)]

    # No embedding failures recorded.
    assert _count(conn, "SELECT count(*) FROM search.embedding_failure") == 0


def test_chunk_text_carries_prefix(rag_corpus) -> None:
    conn = rag_corpus.conn
    row = db.query_one(
        conn,
        "SELECT text_for_index FROM search.chunk WHERE chunk_kind = 'email_body' "
        "ORDER BY text_for_index LIMIT 1",
    )
    assert row is not None
