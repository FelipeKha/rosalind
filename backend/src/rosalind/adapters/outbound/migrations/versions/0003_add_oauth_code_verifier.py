"""add code_verifier and consumed_at to oauth_auth_request

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oauth_auth_request", sa.Column("code_verifier", sa.Text(), nullable=True)
    )
    op.add_column(
        "oauth_auth_request",
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("oauth_auth_request", "consumed_at")
    op.drop_column("oauth_auth_request", "code_verifier")
