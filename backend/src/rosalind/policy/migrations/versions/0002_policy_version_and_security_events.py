"""add account policy versions and security events

Revision ID: 0002_policy_version
Revises: 0001_policy
Create Date: 2026-11-20

``authz.policy_version`` gives the RAG a monotonic per-account counter to key
caches/cursors and audit entries. ``audit.security_event`` records fail-closed
policy loads and L2 verification failures without storing content.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_policy_version"
down_revision = "0001_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_version",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "version", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
        schema="authz",
    )

    op.create_table(
        "security_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="audit",
    )
    op.create_index(
        "ix_security_event_created",
        "security_event",
        ["created_at"],
        schema="audit",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_security_event_created", table_name="security_event", schema="audit"
    )
    op.drop_table("security_event", schema="audit")
    op.drop_table("policy_version", schema="authz")
