"""add core.email_* canonical email tables

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_thread",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("root_message_id", sa.Text(), nullable=False),
        sa.Column("provider_hint", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_account_id"], ["source_account.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_account_id", "root_message_id", name="uq_email_thread_root"
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_email_thread_source_account_id"),
        "email_thread",
        ["source_account_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "email_message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("message_id_synthetic", sa.Boolean(), nullable=False),
        sa.Column("in_reply_to", sa.Text(), nullable=True),
        sa.Column("references", ARRAY(sa.Text()), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("utc_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("text_plain", sa.Text(), nullable=True),
        sa.Column("text_html", sa.Text(), nullable=True),
        sa.Column("has_attachments", sa.Boolean(), nullable=False),
        sa.Column("is_trash_or_spam", sa.Boolean(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("canonicalizer_version", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('received', 'sent', 'self', 'unknown')",
            name="ck_email_message_direction",
        ),
        sa.ForeignKeyConstraint(
            ["source_account_id"], ["source_account.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["core.email_thread.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_account_id", "message_id", name="uq_email_message_source_message"
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_email_message_source_account_id"),
        "email_message",
        ["source_account_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_email_message_thread_id"),
        "email_message",
        ["thread_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "email_message_observation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["raw.source_record.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_record_id", name="uq_email_message_observation_record"
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_email_message_observation_message_id"),
        "email_message_observation",
        ["message_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_email_message_observation_source_record_id"),
        "email_message_observation",
        ["source_record_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "email_participant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("addr", sa.Text(), nullable=False),
        sa.Column("addr_normalized", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "role",
            "addr_normalized",
            name="uq_email_participant_message_role_addr",
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_email_participant_message_id"),
        "email_participant",
        ["message_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "email_attachment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("declared_mime", sa.Text(), nullable=True),
        sa.Column("detected_mime", sa.Text(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("part_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id", "part_index", name="uq_email_attachment_part"
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_email_attachment_message_id"),
        "email_attachment",
        ["message_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "email_tag",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "tag", name="uq_email_tag_message_tag"),
        schema="core",
    )
    op.create_index(
        op.f("ix_email_tag_message_id"),
        "email_tag",
        ["message_id"],
        unique=False,
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("email_tag", schema="core")
    op.drop_table("email_attachment", schema="core")
    op.drop_table("email_participant", schema="core")
    op.drop_table("email_message_observation", schema="core")
    op.drop_table("email_message", schema="core")
    op.drop_table("email_thread", schema="core")
