"""statement expansion, statement sets, and richer build counters

Revision ID: 0003_semantic_pipeline
Revises: 0002_policy_version
Create Date: 2026-11-20

The semantic pipeline needs a shared, reusable set of protected statements per
account (so two agents with the same rule share findings and overlays) and the
expansion terms that feed candidate generation. Build records gain explicit
counters so the dashboard and the worker can report progress and ETA.

Content-adjacent semantic tables (segments, findings, overlays, jobs) belong to
the data backend's migration chain, not this one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0003_semantic_pipeline"
down_revision = "0002_policy_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_expansion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column(
            "terms",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "concepts",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("expansion_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"], ["semantic.protected_statement.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "statement_id",
            "language",
            "expansion_version",
            name="uq_statement_expansion_key",
        ),
        schema="semantic",
    )

    op.create_table(
        "statement_set",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="semantic",
    )
    op.create_index(
        "ix_statement_set_account", "statement_set", ["account_id"], schema="semantic"
    )

    op.create_table(
        "statement_set_member",
        sa.Column("set_id", sa.Text(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column(
            "match_levels",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{asserts,implies,evidence}'::text[]"),
        ),
        sa.Column("treatment_mode", sa.Text(), nullable=False),
        sa.Column("treatment_fallback", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "treatment_mode IN ('redact_span')",
            name="ck_statement_set_member_mode",
        ),
        sa.CheckConstraint(
            "treatment_fallback IN ('drop_segment')",
            name="ck_statement_set_member_fallback",
        ),
        sa.ForeignKeyConstraint(
            ["set_id"], ["semantic.statement_set.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"], ["semantic.protected_statement.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("set_id", "policy_id", "statement_id"),
        schema="semantic",
    )
    op.create_index(
        "ix_statement_set_member_statement",
        "statement_set_member",
        ["statement_id"],
        schema="semantic",
    )

    op.add_column(
        "policy_build",
        sa.Column("segments_total", sa.Integer(), nullable=False, server_default="0"),
        schema="authz",
    )
    op.add_column(
        "policy_build",
        sa.Column("candidates", sa.Integer(), nullable=False, server_default="0"),
        schema="authz",
    )
    op.add_column(
        "policy_build",
        sa.Column("verified", sa.Integer(), nullable=False, server_default="0"),
        schema="authz",
    )
    op.add_column(
        "policy_build",
        sa.Column("flagged", sa.Integer(), nullable=False, server_default="0"),
        schema="authz",
    )
    op.add_column(
        "policy_build",
        sa.Column("pending", sa.Integer(), nullable=False, server_default="0"),
        schema="authz",
    )
    op.add_column(
        "policy_build",
        sa.Column("eta_seconds", sa.Integer(), nullable=True),
        schema="authz",
    )
    op.add_column(
        "policy_build", sa.Column("state", sa.Text(), nullable=True), schema="authz"
    )
    op.add_column(
        "policy_build", sa.Column("error", sa.Text(), nullable=True), schema="authz"
    )


def downgrade() -> None:
    for column in (
        "error",
        "state",
        "eta_seconds",
        "pending",
        "flagged",
        "verified",
        "candidates",
        "segments_total",
    ):
        op.drop_column("policy_build", column, schema="authz")

    op.drop_index(
        "ix_statement_set_member_statement",
        table_name="statement_set_member",
        schema="semantic",
    )
    op.drop_table("statement_set_member", schema="semantic")
    op.drop_index(
        "ix_statement_set_account", table_name="statement_set", schema="semantic"
    )
    op.drop_table("statement_set", schema="semantic")
    op.drop_table("statement_expansion", schema="semantic")
