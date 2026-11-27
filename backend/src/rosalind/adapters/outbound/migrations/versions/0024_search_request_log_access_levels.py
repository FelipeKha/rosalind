"""record enabled access-enforcement levels on search.request_log

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "request_log",
        sa.Column("access_levels", ARRAY(sa.Text()), nullable=True),
        schema="search",
    )


def downgrade() -> None:
    op.drop_column("request_log", "access_levels", schema="search")
