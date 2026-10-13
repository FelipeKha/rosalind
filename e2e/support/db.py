"""Tiny psycopg query helpers shared by the email-RAG e2e tests."""

from __future__ import annotations

import psycopg


def query_all(conn: psycopg.Connection, sql: str, params=None) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(conn: psycopg.Connection, sql: str, params=None):
    rows = query_all(conn, sql, params)
    return rows[0] if rows else None


def message_id_to_email_id(conn: psycopg.Connection) -> dict[str, str]:
    """Map canonical ``message_id`` to the ``email_message.id`` (uuid) it has."""
    rows = query_all(conn, "SELECT message_id, id::text FROM core.email_message")
    return {message_id: str(email_id) for message_id, email_id in rows}
