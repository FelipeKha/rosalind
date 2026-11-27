"""semantic job queue, spot-check queue and redaction audit

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-20

The offline pipeline uses a Postgres-backed queue (no Celery/Redis): jobs are
checkpointed, idempotent and resumable, and the worker picks them with
``FOR UPDATE SKIP LOCKED`` by priority. ``semantic_review_item`` holds the
owner's spot-check queue. ``redaction_event`` records which segments were
redacted for a request, never their content.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("statement_id", sa.Uuid(), nullable=True),
        sa.Column("set_id", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "checkpoint",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
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
            "state IN ('pending', 'running', 'done', 'failed', 'paused')",
            name="ck_semantic_job_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="search",
    )
    op.create_index(
        "semantic_job_pick_idx",
        "semantic_job",
        ["state", "priority", "run_after"],
        schema="search",
    )

    op.create_table(
        "semantic_review_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"], ["search.segment.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="search",
    )
    op.create_index(
        "semantic_review_item_open_idx",
        "semantic_review_item",
        ["resolved", "created_at"],
        schema="search",
    )

    op.create_table(
        "redaction_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("statement_id", sa.Uuid(), nullable=True),
        sa.Column("segment_id", sa.Uuid(), nullable=True),
        sa.Column("segment_hash", sa.Text(), nullable=True),
        sa.Column("treatment", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="search",
    )
    op.create_index(
        "redaction_event_request_idx",
        "redaction_event",
        ["request_id"],
        schema="search",
    )
    op.create_index(
        "redaction_event_created_idx",
        "redaction_event",
        ["created_at"],
        schema="search",
    )


def downgrade() -> None:
    op.drop_index(
        "redaction_event_created_idx", table_name="redaction_event", schema="search"
    )
    op.drop_index(
        "redaction_event_request_idx", table_name="redaction_event", schema="search"
    )
    op.drop_table("redaction_event", schema="search")
    op.drop_index(
        "semantic_review_item_open_idx",
        table_name="semantic_review_item",
        schema="search",
    )
    op.drop_table("semantic_review_item", schema="search")
    op.drop_index("semantic_job_pick_idx", table_name="semantic_job", schema="search")
    op.drop_table("semantic_job", schema="search")
