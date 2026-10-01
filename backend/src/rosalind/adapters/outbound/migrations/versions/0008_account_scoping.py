"""scope source accounts and imports to a Rosalind account

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_account", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_source_account_account_id",
        "source_account",
        "account",
        ["account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_source_account_account_id"),
        "source_account",
        ["account_id"],
        unique=False,
    )

    op.add_column("imports", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_imports_account_id",
        "imports",
        "account",
        ["account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_imports_account_id"),
        "imports",
        ["account_id"],
        unique=False,
    )

    # Pre-authn data is only attributable when a single account exists. In that
    # case backfill everything to it; otherwise rows stay unowned (account_id is
    # NULL) and are invisible until explicitly claimed.
    bind = op.get_bind()
    account_count = bind.execute(sa.text("SELECT COUNT(*) FROM account")).scalar()
    if account_count == 1:
        bind.execute(
            sa.text(
                "UPDATE source_account SET account_id = (SELECT id FROM account) "
                "WHERE account_id IS NULL"
            )
        )
        bind.execute(
            sa.text(
                "UPDATE imports SET account_id = (SELECT id FROM account) "
                "WHERE account_id IS NULL"
            )
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_imports_account_id"), table_name="imports")
    op.drop_constraint("fk_imports_account_id", "imports")
    op.drop_column("imports", "account_id")

    op.drop_index(op.f("ix_source_account_account_id"), table_name="source_account")
    op.drop_constraint("fk_source_account_account_id", "source_account")
    op.drop_column("source_account", "account_id")
