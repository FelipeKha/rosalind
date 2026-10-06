"""add search schema (chunk, chunk_build)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS search")

    op.create_table(
        "chunk",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_kind", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text_for_display", sa.Text(), nullable=False),
        sa.Column("text_for_index", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("index_version", sa.Text(), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("source_account_num", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender_handle", sa.Text(), nullable=False),
        sa.Column("recipient_handles", ARRAY(sa.Text()), nullable=False),
        sa.Column("participant_handles", ARRAY(sa.Text()), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("has_attachment", sa.Boolean(), nullable=False),
        sa.Column("is_trash_or_spam", sa.Boolean(), nullable=False),
        sa.Column("tags", ARRAY(sa.Text()), nullable=False),
        sa.Column("meta", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "chunk_kind IN ('email_body', 'email_quote', 'attachment')",
            name="ck_chunk_kind",
        ),
        sa.CheckConstraint(
            "direction IN ('received', 'sent', 'self', 'unknown')",
            name="ck_chunk_direction",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["core.email_attachment.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["core.email_thread.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "email_id",
            "chunk_kind",
            "attachment_id",
            "seq",
            name="uq_chunk_key",
            postgresql_nulls_not_distinct=True,
        ),
        schema="search",
    )
    op.create_index(
        "chunk_scope_time_idx",
        "chunk",
        ["source_account_num", "sent_at"],
        unique=False,
        schema="search",
    )
    op.create_index(
        "chunk_sender_idx",
        "chunk",
        ["sender_handle"],
        unique=False,
        schema="search",
    )
    op.create_index(
        "chunk_thread_idx",
        "chunk",
        ["thread_id"],
        unique=False,
        schema="search",
    )
    op.create_index(
        "chunk_email_idx",
        "chunk",
        ["email_id"],
        unique=False,
        schema="search",
    )
    op.create_index(
        "chunk_recipients_idx",
        "chunk",
        ["recipient_handles"],
        unique=False,
        schema="search",
        postgresql_using="gin",
    )
    op.create_index(
        "chunk_participants_idx",
        "chunk",
        ["participant_handles"],
        unique=False,
        schema="search",
        postgresql_using="gin",
    )
    op.create_index(
        "chunk_tags_idx",
        "chunk",
        ["tags"],
        unique=False,
        schema="search",
        postgresql_using="gin",
    )
    op.create_index(
        "chunk_list_idx",
        "chunk",
        ["source_account_num", "sent_at", "email_id"],
        unique=False,
        schema="search",
        postgresql_where=sa.text("chunk_kind = 'email_body' AND seq = 0"),
    )

    op.create_table(
        "chunk_build",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_kind", sa.Text(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("index_version", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.Text(), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('done', 'empty', 'failed')", name="ck_chunk_build_status"
        ),
        sa.ForeignKeyConstraint(
            ["email_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["core.email_attachment.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "email_id",
            "chunk_kind",
            "attachment_id",
            name="uq_chunk_build_key",
            postgresql_nulls_not_distinct=True,
        ),
        schema="search",
    )


def downgrade() -> None:
    op.drop_table("chunk_build", schema="search")
    op.drop_table("chunk", schema="search")
