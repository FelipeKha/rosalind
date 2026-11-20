"""add role-specific participant handles to search.chunk

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-20

Access policies can address participants by role (from/to/cc/bcc). The chunk
store previously kept only a merged ``recipient_handles`` array, so role-specific
selectors could not be enforced exactly. The arrays are denormalized from
``core.email_participant`` at chunk-build time and backfilled here for existing
rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_ROLES = ("from", "to", "cc", "bcc")


def upgrade() -> None:
    for role in _ROLES:
        op.add_column(
            "chunk",
            sa.Column(
                f"{role}_handles",
                ARRAY(sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::text[]"),
            ),
            schema="search",
        )

    # Backfill from the canonical participant rows. array_agg returns NULL for
    # an empty group, so coalesce to the empty array. The statements are static
    # literals: DDL cannot bind a column name, and keeping the SQL out of
    # string interpolation avoids any injection surface.
    backfill = {
        "from": """
            UPDATE search.chunk AS c
            SET from_handles = COALESCE(
                (
                    SELECT array_agg(DISTINCT p.addr_normalized)
                    FROM core.email_participant AS p
                    WHERE p.message_id = c.email_id AND p.role = 'from'
                ),
                '{}'::text[]
            )
        """,
        "to": """
            UPDATE search.chunk AS c
            SET to_handles = COALESCE(
                (
                    SELECT array_agg(DISTINCT p.addr_normalized)
                    FROM core.email_participant AS p
                    WHERE p.message_id = c.email_id AND p.role = 'to'
                ),
                '{}'::text[]
            )
        """,
        "cc": """
            UPDATE search.chunk AS c
            SET cc_handles = COALESCE(
                (
                    SELECT array_agg(DISTINCT p.addr_normalized)
                    FROM core.email_participant AS p
                    WHERE p.message_id = c.email_id AND p.role = 'cc'
                ),
                '{}'::text[]
            )
        """,
        "bcc": """
            UPDATE search.chunk AS c
            SET bcc_handles = COALESCE(
                (
                    SELECT array_agg(DISTINCT p.addr_normalized)
                    FROM core.email_participant AS p
                    WHERE p.message_id = c.email_id AND p.role = 'bcc'
                ),
                '{}'::text[]
            )
        """,
    }
    for role in _ROLES:
        op.execute(backfill[role])
        op.create_index(
            f"chunk_{role}_handles_idx",
            "chunk",
            [f"{role}_handles"],
            unique=False,
            schema="search",
            postgresql_using="gin",
        )


def downgrade() -> None:
    for role in _ROLES:
        op.drop_index(f"chunk_{role}_handles_idx", table_name="chunk", schema="search")
        op.drop_column("chunk", f"{role}_handles", schema="search")
