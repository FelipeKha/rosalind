"""create policy service tables

Revision ID: 0001_policy
Revises:
Create Date: 2026-11-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_policy"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS authz")
    op.execute("CREATE SCHEMA IF NOT EXISTS semantic")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")

    op.create_table(
        "policy",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("principal_kind", sa.Text(), nullable=False),
        sa.Column("policy_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="authz",
    )
    op.create_index("ix_policy_account", "policy", ["account_id"], schema="authz")

    op.create_table(
        "policy_revision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_encrypted", sa.Text(), nullable=False),
        sa.Column("interpreter_version", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["authz.policy.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id", "revision", name="uq_policy_revision_policy_revision"
        ),
        schema="authz",
    )

    op.create_table(
        "policy_build",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("coverage_processed", sa.Integer(), nullable=False),
        sa.Column("coverage_total", sa.Integer(), nullable=True),
        sa.Column("classifier_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["authz.policy.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id", "revision", name="uq_policy_build_policy_revision"
        ),
        schema="authz",
    )

    op.create_table(
        "policy_draft",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="authz",
    )
    op.create_index(
        "ix_policy_draft_expires", "policy_draft", ["expires_at"], schema="authz"
    )

    op.create_table(
        "protected_statement",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_encrypted", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="semantic",
    )
    op.create_index(
        "ix_protected_statement_account",
        "protected_statement",
        ["account_id"],
        schema="semantic",
    )

    op.create_table(
        "policy_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("principal_kind", sa.Text(), nullable=False),
        sa.Column("interpreter_version", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="audit",
    )


def downgrade() -> None:
    op.drop_table("policy_event", schema="audit")
    op.drop_index(
        "ix_protected_statement_account",
        table_name="protected_statement",
        schema="semantic",
    )
    op.drop_table("protected_statement", schema="semantic")
    op.drop_index("ix_policy_draft_expires", table_name="policy_draft", schema="authz")
    op.drop_table("policy_draft", schema="authz")
    op.drop_table("policy_build", schema="authz")
    op.drop_table("policy_revision", schema="authz")
    op.drop_index("ix_policy_account", table_name="policy", schema="authz")
    op.drop_table("policy", schema="authz")
    op.execute("DROP SCHEMA IF EXISTS audit")
    op.execute("DROP SCHEMA IF EXISTS semantic")
    op.execute("DROP SCHEMA IF EXISTS authz")
