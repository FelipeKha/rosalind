"""add search.request_log (minimal search trace summary)

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("plan_fingerprint", sa.Text(), nullable=False),
        sa.Column("mode_requested", sa.Text(), nullable=False),
        sa.Column("mode_effective", sa.Text(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("index_version", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("embedding_version", sa.Text(), nullable=True),
        sa.Column("reranker_version", sa.Text(), nullable=True),
        sa.Column("filter_names", ARRAY(sa.Text()), nullable=False),
        sa.Column("filter_sizes", JSONB(), nullable=False),
        sa.Column("lexical_count", sa.Integer(), nullable=True),
        sa.Column("lexical_exhausted", sa.Boolean(), nullable=True),
        sa.Column("lexical_filter_path", sa.Text(), nullable=True),
        sa.Column("semantic_count", sa.Integer(), nullable=True),
        sa.Column("semantic_complete", sa.Boolean(), nullable=True),
        sa.Column("semantic_filter_path", sa.Text(), nullable=True),
        sa.Column("semantic_scan_limit_hit", sa.Boolean(), nullable=True),
        sa.Column("fused_count", sa.Integer(), nullable=True),
        sa.Column("dropped_by_item_cap", sa.Integer(), nullable=True),
        sa.Column("rerank_applied", sa.Boolean(), nullable=True),
        sa.Column("rerank_model", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("warnings", ARRAY(sa.Text()), nullable=False),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("timings_ms", JSONB(), nullable=False),
        sa.Column("returned_chunk_ids", ARRAY(sa.Uuid()), nullable=False),
        sa.Column("returned_item_ids", ARRAY(sa.Uuid()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="search",
    )
    op.create_index(
        "request_log_account_created_idx",
        "request_log",
        ["account_id", "created_at"],
        unique=False,
        schema="search",
    )
    op.create_index(
        "request_log_created_idx",
        "request_log",
        ["created_at"],
        unique=False,
        schema="search",
    )


def downgrade() -> None:
    op.drop_index("request_log_created_idx", table_name="request_log", schema="search")
    op.drop_index(
        "request_log_account_created_idx", table_name="request_log", schema="search"
    )
    op.drop_table("request_log", schema="search")
