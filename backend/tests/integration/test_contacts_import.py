from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind.adapters import composition
from rosalind.adapters.inbound.ingestion.google.parser import GooglePersonParser
from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application.canonicalization.person import CanonicalizationService
from rosalind.application.ports.providers import ContactsFetch, ProviderCredentials
from rosalind.application.services.processing import ProcessingService
from rosalind.domain.source import SourceAccount
from tests._account import ensure_account


class _FakePeopleGateway:
    def __init__(self, contacts: list[dict], sync_token: str | None) -> None:
        self._contacts = contacts
        self._sync_token = sync_token

    def fetch_profile(self, credentials: ProviderCredentials) -> dict:
        raise NotImplementedError

    def fetch_contacts(self, credentials: ProviderCredentials) -> ContactsFetch:
        return ContactsFetch(
            contacts=tuple(self._contacts),
            next_sync_token=self._sync_token,
            sync_parameters={
                "sort_order": "LAST_MODIFIED_ASCENDING",
                "person_fields": ["names", "emailAddresses"],
            },
        )


def _contact(resource_name: str, given: str, family: str, email: str) -> dict:
    contact_id = resource_name.split("/")[1]
    return {
        "resourceName": resource_name,
        "metadata": {"sources": [{"type": "CONTACT", "id": contact_id}]},
        "names": [
            {
                "displayName": f"{given} {family}",
                "givenName": given,
                "familyName": family,
            }
        ],
        "emailAddresses": [{"value": email}],
    }


def _service(gateway: _FakePeopleGateway) -> ProcessingService:
    parser = GooglePersonParser()
    return ProcessingService(
        parsers={parser.resource_type: parser},
        person_parser=parser,
        people=gateway,  # type: ignore[arg-type]
        sources=composition.source_service,
        canonicalizer=CanonicalizationService(),
    )


def _setup(uow: SqlAlchemyUnitOfWork) -> tuple[UUID, SourceAccount]:
    account_id = ensure_account(uow).id
    source = composition.source_service.create_source(
        uow, account_id, provider="google", name="google-personal"
    )
    uow.credentials.upsert(
        account_id=source.id,
        provider="google",
        access_token="test-token",
        refresh_token=None,
        scopes=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    uow.commit()
    return account_id, source


def test_import_api_contacts_ingests_and_stores_sync_token(
    db_session: Session, uow: SqlAlchemyUnitOfWork
) -> None:
    account_id, source = _setup(uow)
    gateway = _FakePeopleGateway(
        [
            _contact("people/c1", "Alice", "Smith", "alice@example.com"),
            _contact("people/c2", "Bob", "Jones", "bob@example.com"),
        ],
        sync_token="sync-token-abc",
    )
    service = _service(gateway)

    import_ = uow.imports.create(
        account_id=account_id, source_account_id=source.id, type_="api"
    )
    outcome = service.import_api_contacts(uow, source, import_)
    uow.commit()

    assert outcome.people_created == 2
    assert outcome.facts_created == 4  # 2 names + 2 emails
    assert outcome.facts_reused == 0
    assert outcome.assertions_created == 4

    assert len(db_session.scalars(select(models.SourceRecord)).all()) == 2
    assert len(db_session.scalars(select(models.Person)).all()) == 2

    account_model = db_session.scalars(
        select(models.SourceAccount).where(models.SourceAccount.id == source.id)
    ).one()
    assert account_model.metadata_["google"]["sync_token"] == "sync-token-abc"
    assert account_model.metadata_["google"]["sync_parameters"]["sort_order"] == (
        "LAST_MODIFIED_ASCENDING"
    )


def test_import_api_contacts_is_idempotent(
    db_session: Session, uow: SqlAlchemyUnitOfWork
) -> None:
    account_id, source = _setup(uow)
    gateway = _FakePeopleGateway(
        [_contact("people/c1", "Alice", "Smith", "alice@example.com")],
        sync_token="sync-token-abc",
    )
    service = _service(gateway)

    first = uow.imports.create(
        account_id=account_id, source_account_id=source.id, type_="api"
    )
    service.import_api_contacts(uow, source, first)
    uow.commit()

    second = uow.imports.create(
        account_id=account_id, source_account_id=source.id, type_="api"
    )
    outcome = service.import_api_contacts(uow, source, second)
    uow.commit()

    assert outcome.people_created == 0
    assert outcome.facts_created == 0
    assert len(db_session.scalars(select(models.Person)).all()) == 1
    assert len(db_session.scalars(select(models.SourceRecord)).all()) == 1


def test_import_api_contacts_skips_unparseable_contact(
    db_session: Session, uow: SqlAlchemyUnitOfWork
) -> None:
    account_id, source = _setup(uow)
    gateway = _FakePeopleGateway(
        [
            _contact("people/c1", "Alice", "Smith", "alice@example.com"),
            {"resourceName": "people/bad", "names": "not-a-list"},
        ],
        sync_token="sync-token-abc",
    )
    service = _service(gateway)

    import_ = uow.imports.create(
        account_id=account_id, source_account_id=source.id, type_="api"
    )
    outcome = service.import_api_contacts(uow, source, import_)
    uow.commit()

    assert outcome.people_created == 1
    assert outcome.message is not None
    assert "1 contact(s) failed" in outcome.message

    # The bad contact's raw payload is retained; only one person canonicalized.
    assert len(db_session.scalars(select(models.SourceRecord)).all()) == 2
    assert len(db_session.scalars(select(models.Person)).all()) == 1
