import uuid
from types import SimpleNamespace

from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence.repositories.person import (
    PostgresPersonRepository,
)
from rosalind.application.services.people import MAX_SEARCH_RESULTS, PersonService


def test_to_profile_maps_all_fields() -> None:
    person_id = uuid.uuid4()
    row = SimpleNamespace(
        person_id=person_id,
        display_name="Alex Morgan",
        given_name="Alex",
        family_name="Morgan",
        primary_email="alex.morgan@example.com",
        email_verified=True,
        gender="female",
        locale="en-GB",
        birth_year=1988,
        birth_month=4,
        birth_day=17,
    )

    profile = PostgresPersonRepository._to_profile(row)

    assert profile.person_id == person_id
    assert profile.display_name == "Alex Morgan"
    assert profile.given_name == "Alex"
    assert profile.family_name == "Morgan"
    assert profile.primary_email == "alex.morgan@example.com"
    assert profile.email_verified is True
    assert profile.gender == "female"
    assert profile.locale == "en-GB"
    assert profile.birth_year == 1988
    assert profile.birth_month == 4
    assert profile.birth_day == 17


def test_to_profile_maps_nulls() -> None:
    row = SimpleNamespace(
        person_id=uuid.uuid4(),
        display_name=None,
        given_name=None,
        family_name=None,
        primary_email=None,
        email_verified=None,
        gender=None,
        locale=None,
        birth_year=None,
        birth_month=None,
        birth_day=None,
    )

    profile = PostgresPersonRepository._to_profile(row)

    assert profile.display_name is None
    assert profile.email_verified is None
    assert profile.birth_year is None


def test_search_people_clamps_limit() -> None:
    class FakeRepo:
        def __init__(self) -> None:
            self.seen_limit: int | None = None

        def search(self, db: Session, query: str, limit: int) -> list:
            self.seen_limit = limit
            return []

        def get(self, db: Session, person_id: uuid.UUID):
            return None

    repo = FakeRepo()
    PersonService(repo).search_people(object(), "Alex")  # type: ignore[arg-type]

    assert repo.seen_limit == MAX_SEARCH_RESULTS
