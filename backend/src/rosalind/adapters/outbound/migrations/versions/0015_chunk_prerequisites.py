"""add source_account.num, email_text.segments_digest, attachment_text.text_sha256

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Scope-predicate surrogate. Integer-typed for index pushdown (see
    # docs/features/chunk_schema.sql); identity so the value is assigned by
    # the database and never derived from a provider concept.
    op.add_column(
        "source_account",
        sa.Column(
            "num",
            sa.Integer(),
            sa.Identity(always=True),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_source_account_num", "source_account", ["num"])

    op.add_column(
        "email_text",
        sa.Column("segments_digest", sa.Text(), nullable=True),
        schema="derived",
    )

    op.add_column(
        "attachment_text",
        sa.Column("text_sha256", sa.Text(), nullable=True),
        schema="derived",
    )


def downgrade() -> None:
    op.drop_column("attachment_text", "text_sha256", schema="derived")
    op.drop_column("email_text", "segments_digest", schema="derived")
    op.drop_constraint("uq_source_account_num", "source_account", type_="unique")
    op.drop_column("source_account", "num")
