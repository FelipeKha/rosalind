"""record semantic-enforcement set and levels on search.request_log

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-20

The semantic columns stay null whenever semantic enforcement is off, so an
existing request log is unchanged for legacy traffic. ``semantic_set_id`` keys
the overlay set used for the request; ``semantic_levels`` records which stages
were enabled, mirroring ``access_levels``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "request_log",
        sa.Column("semantic_set_id", sa.Text(), nullable=True),
        schema="search",
    )
    op.add_column(
        "request_log",
        sa.Column("semantic_policy_version", sa.Integer(), nullable=True),
        schema="search",
    )
    op.add_column(
        "request_log",
        sa.Column("semantic_levels", ARRAY(sa.Text()), nullable=True),
        schema="search",
    )


def downgrade() -> None:
    op.drop_column("request_log", "semantic_levels", schema="search")
    op.drop_column("request_log", "semantic_policy_version", schema="search")
    op.drop_column("request_log", "semantic_set_id", schema="search")
