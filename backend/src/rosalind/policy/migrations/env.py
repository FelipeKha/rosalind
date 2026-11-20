"""Alembic environment for the policy service.

Separate version table from the warehouse so the service can migrate on its
own cadence while sharing PostgreSQL.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from rosalind.config import settings
from rosalind.policy.adapters.persistence import PolicyBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = PolicyBase.metadata

MANAGED_SCHEMAS = frozenset({"authz", "semantic", "audit"})


def include_object(obj, name, type_, reflected, compare_to):
    """Keep autogenerate scoped to the policy-owned schemas.

    The shared database contains warehouse tables and ``account``. They must
    never appear in a policy autogenerate diff. Foreign keys to ``account`` are
    declared in the migration but intentionally absent from the ORM metadata,
    so they are ignored during comparison too.
    """
    del name, reflected, compare_to
    if type_ == "table":
        return obj.schema in MANAGED_SCHEMAS
    if type_ in {"column", "index", "unique_constraint"}:
        return obj.table.schema in MANAGED_SCHEMAS
    if type_ == "foreign_key_constraint":
        if obj.table.schema not in MANAGED_SCHEMAS:
            return False
        return all(
            element.column.table.schema in MANAGED_SCHEMAS for element in obj.elements
        )
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="alembic_version_policy",
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table="alembic_version_policy",
            include_schemas=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
