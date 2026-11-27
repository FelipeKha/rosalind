"""semantic segment store, findings, coverage and model runs

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-20

The atomic unit of semantic verification is a sentence/clause segment, not the
coarse structural tiling in ``derived.email_segment``. Segments keep offsets
into their field text, a stable content hash (so quoted copies share findings)
and their own embedding. Findings are keyed by ``(text_hash, statement_id)`` so
positives propagate; negatives never do.

``search.chunk.replaced_in_sets`` lets retrieval exclude a base chunk for a
semantic set without an anti-join. It is maintained in the same transaction as
the overlay row that replaces it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy.halfvec import HALFVEC
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chunk",
        sa.Column(
            "replaced_in_sets",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        schema="search",
    )
    op.create_index(
        "chunk_replaced_in_sets_idx",
        "chunk",
        ["replaced_in_sets"],
        schema="search",
        postgresql_using="gin",
    )

    op.create_table(
        "segment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column(
            "is_quoted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("segmentation_version", sa.Text(), nullable=False),
        sa.Column("embedding", HALFVEC(1024), nullable=True),
        sa.Column("embedding_text_sha256", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "field IN ('subject', 'body', 'quoted', 'attachment', 'attachment_name')",
            name="ck_segment_field",
        ),
        sa.ForeignKeyConstraint(
            ["email_id"], ["core.email_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["core.email_attachment.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["search.chunk.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "email_id",
            "field",
            "attachment_id",
            "ordinal",
            name="uq_segment_key",
            postgresql_nulls_not_distinct=True,
        ),
        schema="search",
    )
    op.create_index(
        "segment_email_idx", "segment", ["email_id", "field"], schema="search"
    )
    op.create_index("segment_chunk_idx", "segment", ["chunk_id"], schema="search")
    op.create_index("segment_hash_idx", "segment", ["text_hash"], schema="search")
    op.create_index(
        "segment_emb_hnsw",
        "segment",
        ["embedding"],
        schema="search",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )

    op.create_table(
        "finding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column(
            "subject_matches",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "spans",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("classifier_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "verdict IN ('asserts', 'implies', 'evidence', 'none')",
            name="ck_finding_verdict",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"], ["search.segment.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "text_hash", "statement_id", name="uq_finding_text_statement"
        ),
        schema="derived",
    )
    op.create_index("finding_segment_idx", "finding", ["segment_id"], schema="derived")

    op.create_table(
        "finding_override",
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column(
            "disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("text_hash", "statement_id"),
        schema="derived",
    )

    op.create_table(
        "semantic_coverage",
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("classifier_version", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"], ["search.segment.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("segment_id", "statement_id", "stage"),
        schema="search",
    )

    op.create_table(
        "semantic_candidate",
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"], ["search.segment.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("segment_id", "statement_id", "source"),
        schema="search",
    )

    op.create_table(
        "semantic_model_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("quantization", sa.Text(), nullable=True),
        sa.Column("runtime_version", sa.Text(), nullable=False),
        sa.Column("prompt_template_version", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column(
            "window_config",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("classifier_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("classifier_version", name="uq_semantic_model_run_version"),
        schema="search",
    )


def downgrade() -> None:
    op.drop_table("semantic_model_run", schema="search")
    op.drop_table("semantic_candidate", schema="search")
    op.drop_table("semantic_coverage", schema="search")
    op.drop_table("finding_override", schema="derived")
    op.drop_index("finding_segment_idx", table_name="finding", schema="derived")
    op.drop_table("finding", schema="derived")
    op.drop_index("segment_emb_hnsw", table_name="segment", schema="search")
    op.drop_index("segment_hash_idx", table_name="segment", schema="search")
    op.drop_index("segment_chunk_idx", table_name="segment", schema="search")
    op.drop_index("segment_email_idx", table_name="segment", schema="search")
    op.drop_table("segment", schema="search")
    op.drop_index("chunk_replaced_in_sets_idx", table_name="chunk", schema="search")
    op.drop_column("chunk", "replaced_in_sets", schema="search")
