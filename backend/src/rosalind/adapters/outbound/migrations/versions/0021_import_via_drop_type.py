"""add imports.via, drop imports.type

Import format is tracked per file (``import_files.format``), so the import-level
``type`` is redundant. ``via`` records how the data entered Rosalind (a local
file/folder upload or a provider API pull).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "imports",
        sa.Column("via", sa.Text(), nullable=False, server_default="file"),
    )
    op.execute("UPDATE imports SET via = 'api' WHERE type = 'api'")
    op.alter_column("imports", "via", server_default=None)
    op.drop_column("imports", "type")


def downgrade() -> None:
    op.add_column(
        "imports",
        sa.Column("type", sa.Text(), nullable=False, server_default="folder"),
    )
    op.execute("UPDATE imports SET type = 'api' WHERE via = 'api'")
    op.alter_column("imports", "type", server_default=None)
    op.drop_column("imports", "via")
