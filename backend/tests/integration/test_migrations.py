from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from tests._db import reset_schemas


def test_alembic_upgrade_head_creates_tables(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    reset_schemas(engine)

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
        "account",
        "account_identity",
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
        "person_phone",
        "person_address",
        "person_organization",
        "person_url",
        "person_im",
        "person_note",
        "person_relation",
        "person_nickname",
        "person_name_assertion",
        "person_email_assertion",
        "person_date_assertion",
        "person_gender_assertion",
        "person_locale_assertion",
        "person_phone_assertion",
        "person_address_assertion",
        "person_organization_assertion",
        "person_url_assertion",
        "person_im_assertion",
        "person_note_assertion",
        "person_relation_assertion",
        "person_nickname_assertion",
        "email_message",
        "email_message_observation",
        "email_thread",
        "email_participant",
        "email_attachment",
        "email_tag",
    } <= set(inspector.get_table_names(schema="core"))
    assert {"person_profile"} <= set(inspector.get_view_names(schema="agent"))

    # Leave the shared container clean for subsequent tests (the migration
    # creates the agent.person_profile view, which otherwise blocks drop_all).
    reset_schemas(engine)
    engine.dispose()
