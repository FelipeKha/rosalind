"""add contact fact tables (phone, address, organization, url, im, note, relation, nickname) and enrich person_name

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # person_name enrichment ---------------------------------------------------
    op.drop_constraint("uq_person_name_value", "person_name", schema="core")
    op.add_column(
        "person_name", sa.Column("middle_name", sa.Text(), nullable=True), schema="core"
    )
    op.add_column(
        "person_name", sa.Column("name_prefix", sa.Text(), nullable=True), schema="core"
    )
    op.add_column(
        "person_name", sa.Column("name_suffix", sa.Text(), nullable=True), schema="core"
    )
    op.add_column(
        "person_name",
        sa.Column("previous_family_name", sa.Text(), nullable=True),
        schema="core",
    )
    op.add_column(
        "person_name",
        sa.Column("phonetic_given_name", sa.Text(), nullable=True),
        schema="core",
    )
    op.add_column(
        "person_name",
        sa.Column("phonetic_middle_name", sa.Text(), nullable=True),
        schema="core",
    )
    op.add_column(
        "person_name",
        sa.Column("phonetic_family_name", sa.Text(), nullable=True),
        schema="core",
    )
    op.add_column(
        "person_name",
        sa.Column("phonetic_full_name", sa.Text(), nullable=True),
        schema="core",
    )
    op.create_unique_constraint(
        "uq_person_name_value",
        "person_name",
        [
            "person_id",
            "display_name",
            "given_name",
            "family_name",
            "middle_name",
            "name_prefix",
            "name_suffix",
        ],
        schema="core",
        postgresql_nulls_not_distinct=True,
    )

    # person_phone ------------------------------------------------------------
    op.create_table(
        "person_phone",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_normalized", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id", "value_normalized", name="uq_person_phone_person_normalized"
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_phone_person_id"),
        "person_phone",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_phone_one_primary",
        "person_phone",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    # person_address ----------------------------------------------------------
    op.create_table(
        "person_address",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("formatted", sa.Text(), nullable=True),
        sa.Column("street", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id",
            "type",
            "formatted",
            "street",
            "city",
            "region",
            "postal_code",
            "country",
            "country_code",
            name="uq_person_address_value",
            postgresql_nulls_not_distinct=True,
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_address_person_id"),
        "person_address",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_address_one_primary",
        "person_address",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    # person_organization -----------------------------------------------------
    op.create_table(
        "person_organization",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("current", sa.Boolean(), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("start_month", sa.Integer(), nullable=True),
        sa.Column("start_day", sa.Integer(), nullable=True),
        sa.Column("end_year", sa.Integer(), nullable=True),
        sa.Column("end_month", sa.Integer(), nullable=True),
        sa.Column("end_day", sa.Integer(), nullable=True),
        sa.Column("phonetic_name", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "start_month IS NULL OR (start_month BETWEEN 1 AND 12)",
            name="ck_person_organization_start_month",
        ),
        sa.CheckConstraint(
            "end_month IS NULL OR (end_month BETWEEN 1 AND 12)",
            name="ck_person_organization_end_month",
        ),
        sa.CheckConstraint(
            "start_day IS NULL OR start_month IS NOT NULL",
            name="ck_person_organization_start_precision",
        ),
        sa.CheckConstraint(
            "end_day IS NULL OR end_month IS NOT NULL",
            name="ck_person_organization_end_precision",
        ),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id",
            "name",
            "department",
            "title",
            "type",
            "start_year",
            "start_month",
            "start_day",
            name="uq_person_organization_value",
            postgresql_nulls_not_distinct=True,
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_organization_person_id"),
        "person_organization",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_organization_one_primary",
        "person_organization",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    # person_url --------------------------------------------------------------
    op.create_table(
        "person_url",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "value", name="uq_person_url_value"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_url_person_id"),
        "person_url",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_url_one_primary",
        "person_url",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    # person_im ---------------------------------------------------------------
    op.create_table(
        "person_im",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("service", sa.Text(), nullable=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id",
            "service",
            "username",
            "type",
            name="uq_person_im_value",
            postgresql_nulls_not_distinct=True,
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_im_person_id"),
        "person_im",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_im_one_primary",
        "person_im",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    # person_note -------------------------------------------------------------
    op.create_table(
        "person_note",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "value", name="uq_person_note_value"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_note_person_id"),
        "person_note",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_note_one_primary",
        "person_note",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    # person_relation (graph edge) --------------------------------------------
    op.create_table(
        "person_relation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("related_person_id", sa.Uuid(), nullable=True),
        sa.Column("related_person_name", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "related_person_id IS NOT NULL OR related_person_name IS NOT NULL",
            name="ck_person_relation_target",
        ),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["related_person_id"], ["core.person.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id",
            "type",
            "related_person_name",
            name="uq_person_relation_value",
            postgresql_nulls_not_distinct=True,
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_relation_person_id"),
        "person_relation",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_person_relation_related_person_id"),
        "person_relation",
        ["related_person_id"],
        unique=False,
        schema="core",
    )

    # person_nickname ---------------------------------------------------------
    op.create_table(
        "person_nickname",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["core.person.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "value", name="uq_person_nickname_value"),
        schema="core",
    )
    op.create_index(
        op.f("ix_person_nickname_person_id"),
        "person_nickname",
        ["person_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "uq_person_nickname_one_primary",
        "person_nickname",
        ["person_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        schema="core",
    )

    # link tables -------------------------------------------------------------
    _create_assertion_link("person_phone_assertion", "person_phone_id", "person_phone")
    _create_assertion_link(
        "person_address_assertion", "person_address_id", "person_address"
    )
    _create_assertion_link(
        "person_organization_assertion", "person_organization_id", "person_organization"
    )
    _create_assertion_link("person_url_assertion", "person_url_id", "person_url")
    _create_assertion_link("person_im_assertion", "person_im_id", "person_im")
    _create_assertion_link("person_note_assertion", "person_note_id", "person_note")
    _create_assertion_link(
        "person_relation_assertion", "person_relation_id", "person_relation"
    )
    _create_assertion_link(
        "person_nickname_assertion", "person_nickname_id", "person_nickname"
    )


def _create_assertion_link(table: str, fact_column: str, fact_table: str) -> None:
    op.create_table(
        table,
        sa.Column("assertion_id", sa.Uuid(), nullable=False),
        sa.Column(fact_column, sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assertion_id"], ["core.source_assertion.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            [fact_column], [f"core.{fact_table}.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assertion_id"),
        schema="core",
    )
    op.create_index(
        op.f(f"ix_{table}_{fact_column}"),
        table,
        [fact_column],
        unique=False,
        schema="core",
    )


def downgrade() -> None:
    _drop_assertion_link("person_nickname_assertion", "person_nickname")
    _drop_assertion_link("person_relation_assertion", "person_relation")
    _drop_assertion_link("person_note_assertion", "person_note")
    _drop_assertion_link("person_im_assertion", "person_im")
    _drop_assertion_link("person_url_assertion", "person_url")
    _drop_assertion_link("person_organization_assertion", "person_organization")
    _drop_assertion_link("person_address_assertion", "person_address")
    _drop_assertion_link("person_phone_assertion", "person_phone")

    op.drop_table("person_nickname", schema="core")
    op.drop_table("person_relation", schema="core")
    op.drop_table("person_note", schema="core")
    op.drop_table("person_im", schema="core")
    op.drop_table("person_url", schema="core")
    op.drop_table("person_organization", schema="core")
    op.drop_table("person_address", schema="core")
    op.drop_table("person_phone", schema="core")

    op.drop_constraint("uq_person_name_value", "person_name", schema="core")
    op.drop_column("person_name", "phonetic_full_name", schema="core")
    op.drop_column("person_name", "phonetic_family_name", schema="core")
    op.drop_column("person_name", "phonetic_middle_name", schema="core")
    op.drop_column("person_name", "phonetic_given_name", schema="core")
    op.drop_column("person_name", "previous_family_name", schema="core")
    op.drop_column("person_name", "name_suffix", schema="core")
    op.drop_column("person_name", "name_prefix", schema="core")
    op.drop_column("person_name", "middle_name", schema="core")
    op.create_unique_constraint(
        "uq_person_name_value",
        "person_name",
        ["person_id", "display_name", "given_name", "family_name"],
        schema="core",
        postgresql_nulls_not_distinct=True,
    )


def _drop_assertion_link(table: str, fact_table: str) -> None:
    op.drop_table(table, schema="core")
