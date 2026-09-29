import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rosalind.adapters.inbound.ingestion.google.models import GooglePerson
from rosalind.adapters.inbound.ingestion.google.parser import map_google_person

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "google" / "person_profile.json"
)


def _load_person() -> GooglePerson:
    return GooglePerson.model_validate(json.loads(FIXTURE.read_text()))


def test_person_validates() -> None:
    person = _load_person()
    assert person.resourceName == "people/123456789012345678901"
    assert person.names[0].displayName == "Alex Morgan"


def test_validation_requires_resource_name() -> None:
    with pytest.raises(ValidationError):
        GooglePerson.model_validate({"names": []})


def test_unknown_fields_are_preserved() -> None:
    person = GooglePerson.model_validate(
        {"resourceName": "people/1", "somethingCompletelyNew": {"a": 1}}
    )
    assert person.model_extra == {"somethingCompletelyNew": {"a": 1}}


def test_map_collects_union_of_sources() -> None:
    observation = map_google_person(_load_person())
    assert {ref.source_type for ref in observation.source_identities} == {
        "PROFILE",
        "ACCOUNT",
    }


def test_map_preserves_field_paths_and_flags() -> None:
    observation = map_google_person(_load_person())
    email = observation.emails[0]
    assert email.field_path == "$.emailAddresses[0]"
    assert email.source_primary is True
    assert email.source_verified is True
    assert email.value == "alex.morgan@example.com"


def test_map_two_birthday_observations() -> None:
    observation = map_google_person(_load_person())
    assert len(observation.dates) == 2
    assert observation.dates[0].field_path == "$.birthdays[0]"
    assert observation.dates[0].source_primary is True
    assert observation.dates[1].field_path == "$.birthdays[1]"
    assert observation.dates[1].source_primary is None
    assert observation.dates[0].year == 1988


def test_partial_date_maps_zero_to_none() -> None:
    person = GooglePerson.model_validate(
        {"resourceName": "people/1", "birthdays": [{"date": {"year": 1991}}]}
    )
    observation = map_google_person(person)
    assert observation.dates[0].year == 1991
    assert observation.dates[0].month is None
    assert observation.dates[0].day is None


def test_map_is_deterministic() -> None:
    person = _load_person()
    assert map_google_person(person) == map_google_person(person)
