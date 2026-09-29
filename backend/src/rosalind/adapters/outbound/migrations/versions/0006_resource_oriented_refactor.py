"""resource-oriented refactor: source name, import source FK, status split

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # source_account.name is the public/CLI slug; provider + account_identifier
    # remain the immutable provider identity.
    op.add_column("source_account", sa.Column("name", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_source_account_name", "source_account", ["name"])

    # Persist the requested source name across the OAuth callback round-trip.
    op.add_column(
        "oauth_auth_request", sa.Column("source_name", sa.Text(), nullable=True)
    )

    # imports.source (free-text) is replaced by a real FK to source_account.
    op.add_column("imports", sa.Column("source_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_imports_source_account_id",
        "imports",
        "source_account",
        ["source_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_imports_source_account_id"),
        "imports",
        ["source_account_id"],
        unique=False,
    )

    # Split the single status into ingestion and processing dimensions.
    op.alter_column("imports", "status", new_column_name="ingestion_status")
    op.add_column(
        "imports",
        sa.Column(
            "processing_status", sa.Text(), nullable=False, server_default="pending"
        ),
    )
    op.alter_column("imports", "processing_status", server_default=None)
    op.drop_column("imports", "source")

    # Link raw source records back to the import that produced them so that
    # ``process <import-id>`` has a way to select the records to canonicalize.
    op.add_column(
        "source_record",
        sa.Column("import_id", sa.Uuid(), nullable=True),
        schema="raw",
    )
    op.create_foreign_key(
        "fk_source_record_import_id",
        "source_record",
        "imports",
        ["import_id"],
        ["id"],
        ondelete="SET NULL",
        source_schema="raw",
    )
    op.create_index(
        op.f("ix_source_record_import_id"),
        "source_record",
        ["import_id"],
        unique=False,
        schema="raw",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_source_record_import_id"), table_name="source_record", schema="raw"
    )
    op.drop_constraint("fk_source_record_import_id", "source_record", schema="raw")
    op.drop_column("source_record", "import_id", schema="raw")

    op.add_column("imports", sa.Column("source", sa.Text(), nullable=True))
    op.alter_column("imports", "ingestion_status", new_column_name="status")
    op.drop_column("imports", "processing_status")
    op.drop_index(op.f("ix_imports_source_account_id"), table_name="imports")
    op.drop_constraint("fk_imports_source_account_id", "imports")
    op.drop_column("imports", "source_account_id")

    op.drop_constraint("uq_source_account_name", "source_account")
    op.drop_column("source_account", "name")

    op.drop_column("oauth_auth_request", "source_name")
