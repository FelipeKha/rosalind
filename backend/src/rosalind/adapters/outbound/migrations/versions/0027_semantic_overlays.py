"""sanitized chunk and field overlays

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-20

Overlay rows are the precomputed sanitized copy of a chunk for one semantic set
(``set_id``). They carry the same access attributes as the base row so the
step-2 predicates apply unchanged. ``status='provisional'`` means text and
BM25 are ready but the embedding is still pending; the row is then reachable by
lexical search only and never by vector search.

Field overlays cover subjects and attachment names, which are sanitized through
the same path.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy.halfvec import HALFVEC
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunk_overlay",
        sa.Column("set_id", sa.Text(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("index_text", sa.Text(), nullable=False),
        sa.Column(
            "redactions",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("findings_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("embedding", HALFVEC(1024), nullable=True),
        sa.Column("embedding_text_sha256", sa.Text(), nullable=True),
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("source_account_num", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender_handle", sa.Text(), nullable=False),
        sa.Column(
            "recipient_handles",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "participant_handles",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "from_handles",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "to_handles",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "cc_handles",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "bcc_handles",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column(
            "has_attachment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_trash_or_spam",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "tags",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "meta",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('provisional', 'complete')", name="ck_chunk_overlay_status"
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["search.chunk.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["email_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["core.email_thread.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("set_id", "chunk_id"),
        schema="search",
    )
    op.create_index(
        "chunk_overlay_scope_time_idx",
        "chunk_overlay",
        ["source_account_num", "sent_at"],
        schema="search",
    )
    op.create_index(
        "chunk_overlay_sender_idx",
        "chunk_overlay",
        ["sender_handle"],
        schema="search",
    )
    op.create_index(
        "chunk_overlay_participants_idx",
        "chunk_overlay",
        ["participant_handles"],
        schema="search",
        postgresql_using="gin",
    )
    op.create_index(
        "chunk_overlay_emb_hnsw",
        "chunk_overlay",
        ["embedding"],
        schema="search",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )

    op.create_table(
        "field_overlay",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("set_id", sa.Text(), nullable=False),
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("index_text", sa.Text(), nullable=False),
        sa.Column(
            "redactions",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("findings_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('provisional', 'complete')", name="ck_field_overlay_status"
        ),
        sa.ForeignKeyConstraint(
            ["email_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["core.email_attachment.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "set_id",
            "email_id",
            "field",
            "attachment_id",
            name="uq_field_overlay_key",
            postgresql_nulls_not_distinct=True,
        ),
        schema="search",
    )


def downgrade() -> None:
    op.drop_table("field_overlay", schema="search")
    op.drop_index("chunk_overlay_emb_hnsw", table_name="chunk_overlay", schema="search")
    op.drop_index(
        "chunk_overlay_participants_idx",
        table_name="chunk_overlay",
        schema="search",
    )
    op.drop_index(
        "chunk_overlay_sender_idx", table_name="chunk_overlay", schema="search"
    )
    op.drop_index(
        "chunk_overlay_scope_time_idx", table_name="chunk_overlay", schema="search"
    )
    op.drop_table("chunk_overlay", schema="search")
