"""add HNSW index on search.chunk embedding column

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-06
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HNSW maintenance during bulk loads is slow, so create this index after the
    # embedding backfill and only once the benchmark (scripts/bench_semantic_retrieval.py)
    # confirms the ANN path beats the exact path. CONCURRENTLY cannot run inside a
    # transaction, hence the autocommit block. The adapter works without it.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY chunk_emb_bge_m3_v1_hnsw "
            "ON search.chunk USING hnsw (emb_bge_m3_v1 halfvec_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS search.chunk_emb_bge_m3_v1_hnsw")
