"""create raw/core/agent schemas and the person provenance model

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")

    # raw ---------------------------------------------------------------------
    op.create_table(
        "source_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("source_etag", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_account_id"], ["source_account.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_account_id",
            "resource_type",
            "external_id",
            "payload_sha256",
            name="uq_source_record_snapshot",
        ),
        schema="raw",
    )
    op.create_index(
        op.f("ix_source_record_source_account_id"),
        "source_record",
        ["source_account_id"],
        unique=False,
        schema="raw",
    )

    # core --------------------------------------------------------------------
    op.create_table(
        "person",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_table(
        "source_identity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("resource_name", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_account_id"], ["source_account.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_account_id",
            "source_type",
            "external_id",
            name="uq_source_identity_account_type_external",
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_source_identity_person_id"),
        "source_identity",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "source_assertion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("source_identity_id", sa.Uuid(), nullable=True),
        sa.Column("field_path", sa.Text(), nullable=False),
        sa.Column("source_primary", sa.Boolean(), nullable=True),
        sa.Column("source_verified", sa.Boolean(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["raw.source_record.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_identity_id"], ["core.source_identity.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_record_id",
            "field_path",
            name="uq_source_assertion_record_field",
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_source_assertion_source_record_id"),
        "source_assertion",
        ["source_record_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_source_assertion_source_identity_id"),
        "source_assertion",
        ["source_identity_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "person_name",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("given_name", sa.Text(), nullable=True),
        sa.Column("family_name", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_name_person_id"),
        "person_name",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_name_one_primary",
        "person_name",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    op.create_table(
        "person_email",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("email_normalized", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id", "email_normalized", name="uq_person_email_person_normalized"
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_email_person_id"),
        "person_email",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_person_email_normalized",
        "person_email",
        ["email_normalized"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_email_one_primary",
        "person_email",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    op.create_table(
        "person_date",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("date_type", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("day", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "month IS NULL OR (month BETWEEN 1 AND 12)", name="ck_person_date_month"
        ),
        sa.CheckConstraint(
            "day IS NULL OR (day BETWEEN 1 AND 31)", name="ck_person_date_day"
        ),
        sa.CheckConstraint(
            "day IS NULL OR month IS NOT NULL", name="ck_person_date_precision"
        ),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_date_person_id"),
        "person_date",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_date_one_primary",
        "person_date",
        ["person_id", "date_type"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    op.create_table(
        "person_gender",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_gender_person_id"),
        "person_gender",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_gender_one_primary",
        "person_gender",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    op.create_table(
        "person_locale",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_locale_person_id"),
        "person_locale",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_locale_one_primary",
        "person_locale",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    op.create_table(
        "person_name_assertion",
        sa.Column("assertion_id", sa.Uuid(), nullable=False),
        sa.Column("person_name_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assertion_id"], ["core.source_assertion.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["person_name_id"], ["core.person_name.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assertion_id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_name_assertion_person_name_id"),
        "person_name_assertion",
        ["person_name_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "person_email_assertion",
        sa.Column("assertion_id", sa.Uuid(), nullable=False),
        sa.Column("person_email_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assertion_id"], ["core.source_assertion.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["person_email_id"], ["core.person_email.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assertion_id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_email_assertion_person_email_id"),
        "person_email_assertion",
        ["person_email_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "person_date_assertion",
        sa.Column("assertion_id", sa.Uuid(), nullable=False),
        sa.Column("person_date_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assertion_id"], ["core.source_assertion.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["person_date_id"], ["core.person_date.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assertion_id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_date_assertion_person_date_id"),
        "person_date_assertion",
        ["person_date_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "person_gender_assertion",
        sa.Column("assertion_id", sa.Uuid(), nullable=False),
        sa.Column("person_gender_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assertion_id"], ["core.source_assertion.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["person_gender_id"], ["core.person_gender.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assertion_id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_gender_assertion_person_gender_id"),
        "person_gender_assertion",
        ["person_gender_id"],
        unique=False,
        schema="core",
    )

    op.create_table(
        "person_locale_assertion",
        sa.Column("assertion_id", sa.Uuid(), nullable=False),
        sa.Column("person_locale_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assertion_id"], ["core.source_assertion.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["person_locale_id"], ["core.person_locale.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assertion_id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_locale_assertion_person_locale_id"),
        "person_locale_assertion",
        ["person_locale_id"],
        unique=False,
        schema="core",
    )

    # agent -------------------------------------------------------------------
    op.execute(
        """
        CREATE VIEW agent.person_profile AS
        SELECT
            p.id AS person_id,
            n.display_name,
            n.given_name,
            n.family_name,
            e.email AS primary_email,
            e.is_verified AS email_verified,
            g.value AS gender,
            l.value AS locale,
            d.year AS birth_year,
            d.month AS birth_month,
            d.day AS birth_day
        FROM core.person p
        LEFT JOIN core.person_name n
            ON n.person_id = p.id AND n.is_primary
        LEFT JOIN core.person_email e
            ON e.person_id = p.id AND e.is_primary
        LEFT JOIN core.person_gender g
            ON g.person_id = p.id AND g.is_primary
        LEFT JOIN core.person_locale l
            ON l.person_id = p.id AND l.is_primary
        LEFT JOIN core.person_date d
            ON d.person_id = p.id AND d.is_primary AND d.date_type = 'birthday'
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS agent.person_profile")

    op.drop_table("person_locale_assertion", schema="core")
    op.drop_table("person_gender_assertion", schema="core")
    op.drop_table("person_date_assertion", schema="core")
    op.drop_table("person_email_assertion", schema="core")
    op.drop_table("person_name_assertion", schema="core")
    op.drop_table("person_locale", schema="core")
    op.drop_table("person_gender", schema="core")
    op.drop_table("person_date", schema="core")
    op.drop_table("person_email", schema="core")
    op.drop_table("person_name", schema="core")
    op.drop_table("source_assertion", schema="core")
    op.drop_table("source_identity", schema="core")
    op.drop_table("person", schema="core")
    op.drop_table("source_record", schema="raw")

    op.execute("DROP SCHEMA IF EXISTS agent")
    op.execute("DROP SCHEMA IF EXISTS core")
    op.execute("DROP SCHEMA IF EXISTS raw")
