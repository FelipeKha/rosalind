"""Shared database helpers for tests.

Centralizes schema reset and migration so tests exercise the real Alembic
migrations (including views like ``agent.person_profile``) instead of a
hand-maintained ``create_all`` approximation.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text


def reset_schemas(engine: Engine) -> None:
    """Drop the Rosalind schemas and public tables, leaving a clean database."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS "
                "import_files, imports, oauth_auth_request, "
                "oauth_credentials, source_account CASCADE"
            )
        )
        # Drop the Alembic version table so migrations re-run from scratch.
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(text("DROP SCHEMA IF EXISTS raw CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS core CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS agent CASCADE"))


def run_migrations(url: str) -> None:
    """Apply Alembic migrations to the given database URL."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def make_migrated_engine(url: str) -> Engine:
    """Create an engine with the real migrated schema applied."""
    engine = create_engine(url)
    reset_schemas(engine)
    run_migrations(url)
    return engine
