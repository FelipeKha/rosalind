from __future__ import annotations

from sqlalchemy import create_engine, inspect

from tests._db import reset_schemas, run_migrations, run_policy_migrations


def test_policy_migrations_create_tables(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    reset_schemas(engine)
    run_migrations(postgres_url)
    run_policy_migrations(postgres_url)

    inspector = inspect(engine)
    assert {"policy", "policy_revision", "policy_build", "policy_draft"} <= set(
        inspector.get_table_names(schema="authz")
    )
    assert {"protected_statement"} <= set(inspector.get_table_names(schema="semantic"))
    assert {"policy_event"} <= set(inspector.get_table_names(schema="audit"))

    reset_schemas(engine)
    engine.dispose()
