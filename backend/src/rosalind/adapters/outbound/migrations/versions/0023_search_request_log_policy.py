"""add access-policy fields to search.request_log

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "request_log", sa.Column("agent_id", sa.Text(), nullable=True), schema="search"
    )
    op.add_column(
        "request_log",
        sa.Column("policy_version", sa.BigInteger(), nullable=True),
        schema="search",
    )
    op.add_column(
        "request_log",
        sa.Column("scope_fingerprint", sa.Text(), nullable=True),
        schema="search",
    )
    op.add_column(
        "request_log",
        sa.Column("policy_decision", sa.Text(), nullable=True),
        schema="search",
    )


def downgrade() -> None:
    op.drop_column("request_log", "policy_decision", schema="search")
    op.drop_column("request_log", "scope_fingerprint", schema="search")
    op.drop_column("request_log", "policy_version", schema="search")
    op.drop_column("request_log", "agent_id", schema="search")
