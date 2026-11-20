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
                "account_identity, import_files, imports, oauth_auth_request, "
                "oauth_credentials, source_account, account CASCADE"
            )
        )
        # Drop the Alembic version tables so migrations re-run from scratch.
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(text("DROP TABLE IF EXISTS alembic_version_policy"))
        conn.execute(text("DROP SCHEMA IF EXISTS raw CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS core CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS agent CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS derived CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS search CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS authz CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS semantic CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS audit CASCADE"))


def run_migrations(url: str) -> None:
    """Apply Alembic migrations to the given database URL."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def run_policy_migrations(url: str) -> None:
    """Apply the policy service's Alembic chain to the given database."""
    cfg = Config("alembic-policy.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def make_migrated_engine(url: str) -> Engine:
    """Create an engine with the real migrated schema applied."""
    engine = create_engine(url)
    reset_schemas(engine)
    run_migrations(url)
    run_policy_migrations(url)
    return engine
