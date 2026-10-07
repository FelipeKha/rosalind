"""add core.email_message thread_changed_at

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_message",
        sa.Column("thread_changed_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.add_column(
        "email_thread",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.execute(
        "UPDATE core.email_thread SET created_at = now() WHERE created_at IS NULL"
    )
    op.alter_column(
        "email_thread",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        schema="core",
    )


def downgrade() -> None:
    op.drop_column("email_thread", "created_at", schema="core")
    op.drop_column("email_message", "thread_changed_at", schema="core")
