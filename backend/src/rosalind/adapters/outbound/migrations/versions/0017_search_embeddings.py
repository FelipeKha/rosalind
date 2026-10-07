"""add search embedding columns, embedding_failure, embedding_run

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy.halfvec import HALFVEC

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector provides halfvec; required for the embedding column below.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "chunk",
        sa.Column("emb_bge_m3_v1", HALFVEC(1024), nullable=True),
        schema="search",
    )
    op.add_column(
        "chunk",
        sa.Column("emb_bge_m3_v1_text_sha256", sa.Text(), nullable=True),
        schema="search",
    )

    op.create_table(
        "embedding_failure",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("space", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["search.chunk.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id", "space"),
        schema="search",
    )

    op.create_table(
        "embedding_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("device_class", sa.Text(), nullable=False),
        sa.Column("dtype", sa.Text(), nullable=False),
        sa.Column("revision", sa.Text(), nullable=False),
        sa.Column("locality", sa.Text(), nullable=False),
        sa.Column("chunks_embedded", sa.Integer(), nullable=False),
        sa.Column("chunks_failed", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="search",
    )


def downgrade() -> None:
    op.drop_table("embedding_run", schema="search")
    op.drop_table("embedding_failure", schema="search")
    op.drop_column("chunk", "emb_bge_m3_v1_text_sha256", schema="search")
    op.drop_column("chunk", "emb_bge_m3_v1", schema="search")
