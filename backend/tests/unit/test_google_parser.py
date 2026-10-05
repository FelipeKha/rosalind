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


def _person_with_contact_fields() -> GooglePerson:
    return GooglePerson.model_validate(
        {
            "resourceName": "people/1",
            "names": [
                {
                    "displayName": "Jane Smith",
                    "givenName": "Jane",
                    "familyName": "Smith",
                    "middleName": "Anne",
                    "honorificPrefix": "Dr.",
                    "honorificSuffix": "Jr.",
                    "phoneticGivenName": "Jayn",
                }
            ],
            "phoneNumbers": [
                {
                    "value": "+1 (415) 555-2671",
                    "type": "mobile",
                    "metadata": {"primary": True},
                }
            ],
            "addresses": [
                {
                    "formattedValue": "1 Infinite Loop",
                    "type": "work",
                    "streetAddress": "1 Infinite Loop",
                    "city": "Cupertino",
                    "region": "CA",
                    "postalCode": "95014",
                    "country": "USA",
                    "countryCode": "US",
                }
            ],
            "organizations": [
                {
                    "name": "Acme Corp",
                    "department": "Engineering",
                    "title": "Staff Engineer",
                    "type": "work",
                    "current": True,
                    "startDate": {"year": 2020, "month": 3},
                }
            ],
            "urls": [{"value": "https://example.com", "type": "home"}],
            "imClients": [{"username": "jane.smith", "protocol": "googleTalk"}],
            "biographies": [{"value": "Hello world", "contentType": "TEXT_PLAIN"}],
            "relations": [{"person": "John Smith", "type": "spouse"}],
            "nicknames": [{"value": "Janey", "type": "default"}],
        }
    )


def test_map_contact_fields() -> None:
    observation = map_google_person(_person_with_contact_fields())

    name = observation.names[0]
    assert name.middle_name == "Anne"
    assert name.name_prefix == "Dr."
    assert name.name_suffix == "Jr."
    assert name.phonetic_given_name == "Jayn"

    phone = observation.phones[0]
    assert phone.value == "+1 (415) 555-2671"
    assert phone.type == "mobile"
    assert phone.source_primary is True

    address = observation.addresses[0]
    assert address.street == "1 Infinite Loop"
    assert address.city == "Cupertino"
    assert address.country_code == "US"

    org = observation.organizations[0]
    assert org.name == "Acme Corp"
    assert org.title == "Staff Engineer"
    assert org.current is True
    assert (org.start_year, org.start_month, org.start_day) == (2020, 3, None)

    assert observation.urls[0].value == "https://example.com"
    assert observation.ims[0].service == "googleTalk"
    assert observation.notes[0].content_type == "TEXT_PLAIN"
    assert observation.relations[0].related_person_name == "John Smith"
    assert observation.relations[0].type == "spouse"
    assert observation.nicknames[0].value == "Janey"
