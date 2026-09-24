"""create source_account, oauth_credentials and oauth_auth_request tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_account",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("account_identifier", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "account_identifier",
            name="uq_source_account_provider_identifier",
        ),
    )
    op.create_table(
        "oauth_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("token_type", sa.Text(), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_account_id"], ["source_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_account_id",
            "provider",
            name="uq_oauth_credentials_account_provider",
        ),
    )
    op.create_index(
        op.f("ix_oauth_credentials_source_account_id"),
        "oauth_credentials",
        ["source_account_id"],
        unique=False,
    )
    op.create_table(
        "oauth_auth_request",
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_account_id"], ["source_account.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("state"),
    )
    op.create_index(
        op.f("ix_oauth_auth_request_source_account_id"),
        "oauth_auth_request",
        ["source_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_oauth_auth_request_source_account_id"), table_name="oauth_auth_request"
    )
    op.drop_table("oauth_auth_request")
    op.drop_index(
        op.f("ix_oauth_credentials_source_account_id"), table_name="oauth_credentials"
    )
    op.drop_table("oauth_credentials")
    op.drop_table("source_account")
