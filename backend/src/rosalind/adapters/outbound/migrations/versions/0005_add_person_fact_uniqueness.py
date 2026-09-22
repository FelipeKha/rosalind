"""add value-uniqueness constraints to canonical person fact tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_person_name_value",
        "person_name",
        ["person_id", "display_name", "given_name", "family_name"],
        schema="core",
        postgresql_nulls_not_distinct=True,
    )
    op.create_unique_constraint(
        "uq_person_gender_value",
        "person_gender",
        ["person_id", "value"],
        schema="core",
    )
    op.create_unique_constraint(
        "uq_person_locale_value",
        "person_locale",
        ["person_id", "value"],
        schema="core",
    )
    op.create_unique_constraint(
        "uq_person_date_value",
        "person_date",
        ["person_id", "date_type", "year", "month", "day"],
        schema="core",
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_constraint("uq_person_date_value", "person_date", schema="core")
    op.drop_constraint("uq_person_locale_value", "person_locale", schema="core")
    op.drop_constraint("uq_person_gender_value", "person_gender", schema="core")
    op.drop_constraint("uq_person_name_value", "person_name", schema="core")
