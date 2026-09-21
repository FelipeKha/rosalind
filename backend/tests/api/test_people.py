import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from rosalind import models
from rosalind.ingestion import service

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "google" / "person_profile.json"
)


def _ingest(db: Session) -> uuid.UUID:
    account = models.SourceAccount(provider="google", account_identifier="test-account")
    db.add(account)
    db.commit()
    result = service.ingest_person(db, account, json.loads(FIXTURE.read_text()))
    return result.person_id


def test_search_people(
    migrated_api_client: TestClient, migrated_db_session: Session
) -> None:
    _ingest(migrated_db_session)

    response = migrated_api_client.get("/people/search", params={"q": "Alex"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["display_name"] == "Alex Morgan"


def test_get_person(
    migrated_api_client: TestClient, migrated_db_session: Session
) -> None:
    person_id = _ingest(migrated_db_session)

    response = migrated_api_client.get(f"/people/{person_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["person_id"] == str(person_id)
    assert body["primary_email"] == "alex.morgan@example.com"


def test_get_person_not_found(migrated_api_client: TestClient) -> None:
    response = migrated_api_client.get(f"/people/{uuid.uuid4()}")

    assert response.status_code == 404


def test_search_people_requires_query(migrated_api_client: TestClient) -> None:
    response = migrated_api_client.get("/people/search")

    assert response.status_code == 422
