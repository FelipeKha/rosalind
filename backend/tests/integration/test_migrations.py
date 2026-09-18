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
        conn.execute(text("DROP SCHEMA IF EXISTS raw CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS core CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS agent CASCADE"))

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(cfg, "head")

    inspector = inspect(engine)
    assert {
        "imports",
        "import_files",
        "source_account",
        "oauth_credentials",
        "oauth_auth_request",
    } <= set(inspector.get_table_names())
    assert {"source_record"} <= set(inspector.get_table_names(schema="raw"))
    assert {
        "person",
        "source_identity",
        "source_assertion",
        "person_name",
        "person_email",
        "person_date",
        "person_gender",
        "person_locale",
        "person_name_assertion",
        "person_email_assertion",
        "person_date_assertion",
        "person_gender_assertion",
        "person_locale_assertion",
    } <= set(inspector.get_table_names(schema="core"))
    assert {"person_profile"} <= set(inspector.get_view_names(schema="agent"))
    engine.dispose()
