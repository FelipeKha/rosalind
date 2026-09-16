from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrade_head_creates_tables(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS "
                "import_files, imports, oauth_auth_request, "
                "oauth_credentials, source_account CASCADE"
            )
        )

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(cfg, "head")

    tables = set(inspect(engine).get_table_names())
    assert {
        "imports",
        "import_files",
        "source_account",
        "oauth_credentials",
        "oauth_auth_request",
    } <= tables
    engine.dispose()
