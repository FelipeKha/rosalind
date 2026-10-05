"""add derived enrich tables (email_text, email_segment, attachment_text)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS derived")

    op.create_table(
        "email_text",
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("clean_text", sa.Text(), nullable=False),
        sa.Column("clean_method", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stage_version", sa.Text(), nullable=False),
        sa.Column("input_sha256", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('done', 'empty', 'failed')", name="ck_email_text_status"
        ),
        sa.ForeignKeyConstraint(
            ["email_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("email_id"),
        schema="derived",
    )

    op.create_table(
        "email_segment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("language_confidence", sa.Float(), nullable=True),
        sa.Column("quote_depth", sa.Integer(), nullable=False),
        sa.Column("attribution_raw", sa.Text(), nullable=True),
        sa.Column("quoted_author", sa.Text(), nullable=True),
        sa.Column("quoted_at", sa.Text(), nullable=True),
        sa.Column("covered_by_email_id", sa.Uuid(), nullable=True),
        sa.Column("coverage_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('new', 'quoted', 'forwarded', 'signature', 'disclaimer')",
            name="ck_email_segment_kind",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["covered_by_email_id"], ["core.email_message.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_id", "seq", name="uq_email_segment_email_seq"),
        schema="derived",
    )
    op.create_index(
        op.f("ix_derived_email_segment_email_id"),
        "email_segment",
        ["email_id"],
        unique=False,
        schema="derived",
    )

    op.create_table(
        "attachment_text",
        sa.Column("blob_sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("stage_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('done', 'empty', 'needs_ocr', 'unsupported', 'too_large', "
            "'encrypted', 'failed')",
            name="ck_attachment_text_status",
        ),
        sa.PrimaryKeyConstraint("blob_sha256"),
        schema="derived",
    )


def downgrade() -> None:
    op.drop_table("attachment_text", schema="derived")
    op.drop_table("email_segment", schema="derived")
    op.drop_table("email_text", schema="derived")
