from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence.models.person import (
    Person,
    PersonEmail,
    PersonName,
)
from rosalind.adapters.outbound.persistence.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from rosalind.config import ParserModelSettings, PolicySettings
from rosalind.policy.adapters.persistence import PostgresPolicyRepository
from rosalind.policy.adapters.secret_box import FernetSecretBox
from rosalind.policy.api.app import create_app
from rosalind.policy.api.deps import get_current_account, get_service, get_session
from rosalind.policy.application.interpreter import InterpreterService
from rosalind.policy.application.ports import AccountRef
from rosalind.policy.domain.extraction import (
    CanonicalStatement,
    ConstraintDraft,
    EmailSelectorObject,
    ExtractionResult,
    Modality,
    ParticipantMention,
)
from tests._account import ensure_account

SETTINGS = PolicySettings(
    models=[ParserModelSettings(name="fake", model="fake:latest")],
    default_model="fake",
)


class FakeParser:
    def __init__(self, constraints: list[ConstraintDraft]) -> None:
        self._constraints = constraints

    @property
    def model_name(self) -> str:
        return "fake"

    def extract(self, prompt: str) -> ExtractionResult:
        del prompt
        return ExtractionResult(constraints=self._constraints)

    def canonicalize(self, text: str, kind: str) -> CanonicalStatement:
        del text, kind
        return CanonicalStatement(text="The user has cancer")


def _client(session: Session, service: InterpreterService, account_id, person_id):
    app = create_app()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_current_account] = lambda: AccountRef(
        id=account_id, self_person_id=person_id
    )
    return TestClient(app)


def _person(session: Session) -> Person:
    person = Person(id=uuid.uuid4())
    session.add(person)
    session.flush()
    session.add(
        PersonName(person_id=person.id, display_name="John Smith", is_primary=True)
    )
    session.add(
        PersonEmail(
            person_id=person.id,
            email="john@example.com",
            email_normalized="john@example.com",
            is_primary=True,
            is_verified=True,
        )
    )
    session.commit()
    return person


def _draft() -> ConstraintDraft:
    return ConstraintDraft(
        source_span="Agent A can't see emails from John Smith",
        effect="deny",
        principal_mentions=["Agent A"],
        modality=Modality.ACCESS,
        object=EmailSelectorObject(
            participants=[ParticipantMention(mention="John Smith", role_mention="from")]
        ),
    )


def test_api_create_and_confirm(migrated_db_session: Session) -> None:
    account = ensure_account(SqlAlchemyUnitOfWork(migrated_db_session))
    person = _person(migrated_db_session)
    service = InterpreterService(
        repository=PostgresPolicyRepository(migrated_db_session),
        parser_factory=lambda model: FakeParser([_draft()]),
        secret_box=FernetSecretBox(),
        settings=SETTINGS,
    )
    client = _client(migrated_db_session, service, account.id, person.id)

    created = client.post(
        "/v1/policy-drafts",
        json={"prompt": "Agent A can't see emails from John Smith", "model": "fake"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["constraints"][0]["state"] == "ready"

    confirmed = client.post(f"/v1/policy-drafts/{body['draft_id']}/confirm", json={})
    assert confirmed.status_code == 200
    assert confirmed.json()["policies"][0]["status"] == "active"

    policies = client.get("/v1/policies")
    assert policies.status_code == 200
    assert len(policies.json()) == 1


def test_api_rejects_model_outside_allowlist(
    migrated_db_session: Session,
) -> None:
    account = ensure_account(SqlAlchemyUnitOfWork(migrated_db_session))
    service = InterpreterService(
        repository=PostgresPolicyRepository(migrated_db_session),
        parser_factory=lambda model: FakeParser([_draft()]),
        secret_box=FernetSecretBox(),
        settings=SETTINGS,
    )
    client = _client(migrated_db_session, service, account.id, None)

    response = client.post(
        "/v1/policy-drafts",
        json={"prompt": "anything", "model": "hosted-model"},
    )

    assert response.status_code == 422
