"""add core.email_message content_sha256

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_message",
        sa.Column("content_sha256", sa.Text(), nullable=True),
        schema="core",
    )


def downgrade() -> None:
    op.drop_column("email_message", "content_sha256", schema="core")
