"""add raw.source_record payload_uri and make payload nullable

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "source_record",
        "payload",
        existing_type=JSONB(),
        nullable=True,
        schema="raw",
    )
    op.add_column(
        "source_record",
        sa.Column("payload_uri", sa.Text(), nullable=True),
        schema="raw",
    )


def downgrade() -> None:
    op.drop_column("source_record", "payload_uri", schema="raw")
    op.alter_column(
        "source_record",
        "payload",
        existing_type=JSONB(),
        nullable=False,
        schema="raw",
    )
