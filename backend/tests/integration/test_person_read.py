import json
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.repositories.person import (
    PostgresPersonRepository,
)
from rosalind.services import processing
from rosalind.services.people import PersonService

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "google"
    / "person_profile.json"
)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text())


def _ingest(db: Session) -> uuid.UUID:
    account = models.SourceAccount(
        provider="google", account_identifier="test-account"
    )
    db.add(account)
    db.commit()
    result = processing.ingest_person(db, account, _payload())
    return result.person_id


def _service() -> PersonService:
    return PersonService(PostgresPersonRepository())


def test_search_people_finds_by_name(migrated_db_session: Session) -> None:
    _ingest(migrated_db_session)

    results = _service().search_people(migrated_db_session, "Alex")

    assert len(results) == 1
    assert results[0].display_name == "Alex Morgan"


def test_search_people_finds_by_email(migrated_db_session: Session) -> None:
    _ingest(migrated_db_session)

    results = _service().search_people(migrated_db_session, "alex.morgan")

    assert len(results) == 1
    assert results[0].primary_email == "alex.morgan@example.com"


def test_search_people_no_match_is_empty(migrated_db_session: Session) -> None:
    _ingest(migrated_db_session)

    assert _service().search_people(migrated_db_session, "zzz") == []


def test_get_person_returns_resolved_profile(
    migrated_db_session: Session,
) -> None:
    person_id = _ingest(migrated_db_session)

    profile = _service().get_person(migrated_db_session, person_id)

    assert profile is not None
    assert profile.person_id == person_id
    assert profile.display_name == "Alex Morgan"
    assert profile.given_name == "Alex"
    assert profile.family_name == "Morgan"
    assert profile.primary_email == "alex.morgan@example.com"
    assert profile.email_verified is True
    assert profile.gender == "female"
    assert profile.locale == "en-GB"
    assert (profile.birth_year, profile.birth_month, profile.birth_day) == (
        1988,
        4,
        17,
    )


def test_get_person_unknown_returns_none(migrated_db_session: Session) -> None:
    assert _service().get_person(migrated_db_session, uuid.uuid4()) is None
