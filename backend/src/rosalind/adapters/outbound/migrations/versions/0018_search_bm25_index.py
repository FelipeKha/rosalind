"""add pg_search BM25 index on search.chunk

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-06
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_search")

    # Scalar fast fields (scope/time/bools) push down natively. Text filters use
    # the literal tokenizer so exact-match and set filters push into the index.
    # Array columns (recipient/participant/tags) and thread_id are deliberately
    # omitted: ParadeDB applies them as correct heap filters instead.
    op.execute(
        "CREATE INDEX chunk_bm25_idx ON search.chunk USING bm25 ("
        "id, text_for_index, source_account_num, sent_at, has_attachment, "
        "is_trash_or_spam, (sender_handle::pdb.literal), "
        "(direction::pdb.literal), (language::pdb.literal))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS search.chunk_bm25_idx")
