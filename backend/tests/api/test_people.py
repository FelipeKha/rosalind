import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "google" / "person_profile.json"
)


def _ingest(uow: SqlAlchemyUnitOfWork) -> uuid.UUID:
    account = composition.source_service.create_source(
        uow, provider="google", name="test-account"
    )
    result = composition.processing_service.ingest_person(
        uow, account, json.loads(FIXTURE.read_text())
    )
    return result.person_id


def test_search_people(
    migrated_api_client: TestClient, migrated_uow: SqlAlchemyUnitOfWork
) -> None:
    _ingest(migrated_uow)

    response = migrated_api_client.get("/people/search", params={"q": "Alex"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["display_name"] == "Alex Morgan"


def test_get_person(
    migrated_api_client: TestClient, migrated_uow: SqlAlchemyUnitOfWork
) -> None:
    person_id = _ingest(migrated_uow)

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
