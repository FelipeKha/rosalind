import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind.adapters import composition
from rosalind.adapters.inbound.ingestion.google.models import (
    GOOGLE_PERSON_RESOURCE_TYPE,
)
from rosalind.adapters.outbound.persistence import models
from rosalind.application.errors import InvalidPayloadError
from rosalind.application.services.processing import payload_sha256

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "google" / "person_profile.json"
)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text())


def _account(db: Session) -> models.SourceAccount:
    account = models.SourceAccount(provider="google", account_identifier="test-account")
    db.add(account)
    db.commit()
    return account


def test_ingest_person_writes_raw_and_canonical(db_session: Session) -> None:
    account = _account(db_session)
    result = composition.processing_service.ingest_person(
        db_session, account, _payload()
    )

    assert result.created is True
    assert result.facts_created == 5
    assert result.facts_reused == 1  # second birthday observation dedupes to one fact
    assert result.assertions_created == 6

    records = db_session.scalars(select(models.SourceRecord)).all()
    assert len(records) == 1
    record = records[0]
    assert record.resource_type == GOOGLE_PERSON_RESOURCE_TYPE
    assert record.external_id == "people/123456789012345678901"
    assert record.payload_sha256 == payload_sha256(_payload())

    people = db_session.scalars(select(models.Person)).all()
    assert len(people) == 1

    identities = db_session.scalars(select(models.SourceIdentity)).all()
    assert {(i.source_type, i.external_id) for i in identities} == {
        ("PROFILE", "123456789012345678901"),
        ("ACCOUNT", "123456789012345678901"),
    }

    assert len(db_session.scalars(select(models.PersonName)).all()) == 1

    emails = db_session.scalars(select(models.PersonEmail)).all()
    assert len(emails) == 1
    assert emails[0].email == "alex.morgan@example.com"
    assert emails[0].email_normalized == "alex.morgan@example.com"
    assert emails[0].is_primary is True
    assert emails[0].is_verified is True

    dates = db_session.scalars(select(models.PersonDate)).all()
    assert len(dates) == 1
    assert (dates[0].year, dates[0].month, dates[0].day) == (1988, 4, 17)
    assert dates[0].is_primary is True

    assert len(db_session.scalars(select(models.PersonGender)).all()) == 1
    assert len(db_session.scalars(select(models.PersonLocale)).all()) == 1


def test_ingest_person_is_idempotent(db_session: Session) -> None:
    account = _account(db_session)
    first = composition.processing_service.ingest_person(
        db_session, account, _payload()
    )
    second = composition.processing_service.ingest_person(
        db_session, account, _payload()
    )

    assert first.person_id == second.person_id
    assert second.created is False
    assert second.facts_created == 0
    assert second.assertions_created == 0

    assert len(db_session.scalars(select(models.SourceRecord)).all()) == 1
    assert len(db_session.scalars(select(models.Person)).all()) == 1
    assert len(db_session.scalars(select(models.PersonEmail)).all()) == 1
    assert len(db_session.scalars(select(models.SourceAssertion)).all()) == 6


def test_ingest_person_persists_raw_before_validation(db_session: Session) -> None:
    account = _account(db_session)
    bad = {"resourceName": "people/bad", "names": "not-a-list"}

    with pytest.raises(ValidationError):
        composition.processing_service.ingest_person(db_session, account, bad)

    records = db_session.scalars(select(models.SourceRecord)).all()
    assert len(records) == 1
    assert records[0].external_id == "people/bad"
    assert records[0].payload == bad

    assert db_session.scalars(select(models.Person)).all() == []


def test_ingest_person_rejects_missing_resource_name(db_session: Session) -> None:
    account = _account(db_session)
    with pytest.raises(InvalidPayloadError):
        composition.processing_service.ingest_person(db_session, account, {"names": []})

    assert db_session.scalars(select(models.SourceRecord)).all() == []


def test_ingest_person_changed_payload_resolves_same_person(
    db_session: Session,
) -> None:
    account = _account(db_session)
    composition.processing_service.ingest_person(db_session, account, _payload())

    changed = _payload()
    changed["names"][0]["displayName"] = "Alex J. Morgan"
    changed["names"][0]["metadata"]["primary"] = False
    composition.processing_service.ingest_person(db_session, account, changed)

    assert len(db_session.scalars(select(models.SourceRecord)).all()) == 2
    assert len(db_session.scalars(select(models.Person)).all()) == 1

    names = db_session.scalars(select(models.PersonName)).all()
    assert {n.display_name for n in names} == {"Alex Morgan", "Alex J. Morgan"}
