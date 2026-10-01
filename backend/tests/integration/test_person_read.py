import json
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence.repositories.person import (
    PostgresPersonRepository,
)
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application.services.people import PersonService
from tests._account import ensure_account

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "google" / "person_profile.json"
)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text())


def _ingest(uow: SqlAlchemyUnitOfWork) -> tuple[uuid.UUID, uuid.UUID]:
    account_id = ensure_account(uow).id
    account = composition.source_service.create_source(
        uow, account_id, provider="google", name="test-account"
    )
    result = composition.processing_service.ingest_person(uow, account, _payload())
    return result.person_id, account_id


def _service(session: Session) -> PersonService:
    return PersonService(PostgresPersonRepository(session))


def test_search_people_finds_by_name(
    migrated_db_session: Session, migrated_uow: SqlAlchemyUnitOfWork
) -> None:
    _, account_id = _ingest(migrated_uow)

    results = _service(migrated_db_session).search_people(account_id, "Alex")

    assert len(results) == 1
    assert results[0].display_name == "Alex Morgan"


def test_search_people_finds_by_email(
    migrated_db_session: Session, migrated_uow: SqlAlchemyUnitOfWork
) -> None:
    _, account_id = _ingest(migrated_uow)

    results = _service(migrated_db_session).search_people(account_id, "alex.morgan")

    assert len(results) == 1
    assert results[0].primary_email == "alex.morgan@example.com"


def test_search_people_no_match_is_empty(
    migrated_db_session: Session, migrated_uow: SqlAlchemyUnitOfWork
) -> None:
    _, account_id = _ingest(migrated_uow)

    assert _service(migrated_db_session).search_people(account_id, "zzz") == []


def test_get_person_returns_resolved_profile(
    migrated_db_session: Session, migrated_uow: SqlAlchemyUnitOfWork
) -> None:
    person_id, account_id = _ingest(migrated_uow)

    profile = _service(migrated_db_session).get_person(account_id, person_id)

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


def test_get_person_unknown_returns_none(
    migrated_db_session: Session, migrated_uow: SqlAlchemyUnitOfWork
) -> None:
    _, account_id = _ingest(migrated_uow)
    assert _service(migrated_db_session).get_person(account_id, uuid.uuid4()) is None
