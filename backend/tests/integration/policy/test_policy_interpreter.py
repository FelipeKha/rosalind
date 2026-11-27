from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence.models.email import (
    EmailMessage,
    EmailParticipant,
)
from rosalind.adapters.outbound.persistence.models.person import (
    Person,
    PersonEmail,
    PersonName,
)
from rosalind.adapters.outbound.persistence.models.source import SourceAccount
from rosalind.config import ParserModelSettings, PolicySettings
from rosalind.policy.adapters.persistence import (
    PolicyBuildModel,
    PolicyEventModel,
    PolicyModel,
    PolicyRevisionModel,
    PostgresPolicyRepository,
    ProtectedStatementModel,
)
from rosalind.policy.adapters.secret_box import FernetSecretBox
from rosalind.policy.application.interpreter import InterpreterService
from rosalind.policy.domain.drafts import ConstraintStateName
from rosalind.policy.domain.extraction import (
    CanonicalStatement,
    ConstraintDraft,
    EmailSelectorObject,
    ExtractionResult,
    Modality,
    ParticipantMention,
    PropositionObject,
)
from rosalind.security import decrypt_secret
from tests._account import ensure_account

SETTINGS = PolicySettings(
    models=[ParserModelSettings(name="fake", model="fake:latest")],
    default_model="fake",
)


class FakeParser:
    def __init__(
        self, constraints: list[ConstraintDraft], canonical: str = "The user has cancer"
    ) -> None:
        self._constraints = constraints
        self._canonical = canonical

    @property
    def model_name(self) -> str:
        return "fake"

    def extract(self, prompt: str) -> ExtractionResult:
        return ExtractionResult(constraints=self._constraints)

    def canonicalize(self, text: str, kind: str) -> CanonicalStatement:
        del text, kind
        return CanonicalStatement(text=self._canonical)


def _service(session: Session, parser: FakeParser) -> InterpreterService:
    return InterpreterService(
        repository=PostgresPolicyRepository(session),
        parser_factory=lambda model: parser,
        secret_box=FernetSecretBox(),
        settings=SETTINGS,
    )


def _person(session: Session, name: str, email: str) -> Person:
    person = Person(id=uuid.uuid4())
    session.add(person)
    session.flush()
    session.add(PersonName(person_id=person.id, display_name=name, is_primary=True))
    session.add(
        PersonEmail(
            person_id=person.id,
            email=email,
            email_normalized=email.lower(),
            is_primary=True,
            is_verified=True,
        )
    )
    session.commit()
    return person


def _source_account(session: Session, account_id: uuid.UUID) -> SourceAccount:
    account = SourceAccount(
        account_id=account_id,
        provider="google",
        name="work",
        account_identifier="acct-1",
        display_name="Work",
    )
    session.add(account)
    session.commit()
    return account


def _email_from(session: Session, source_account_id: uuid.UUID, addr: str) -> None:
    message = EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source_account_id,
        message_id=f"<{uuid.uuid4()}@example.com>",
        occurred_at=datetime.now(UTC),
        direction="received",
        parser_version="v1",
        canonicalizer_version="v1",
    )
    session.add(message)
    session.flush()
    session.add(
        EmailParticipant(
            message_id=message.id,
            role="from",
            addr=addr,
            addr_normalized=addr.lower(),
            seq=0,
        )
    )
    session.commit()


def _access_draft() -> ConstraintDraft:
    return ConstraintDraft(
        source_span="Agent A can't see emails from John Smith",
        effect="deny",
        principal_mentions=["Agent A"],
        modality=Modality.ACCESS,
        object=EmailSelectorObject(
            participants=[ParticipantMention(mention="John Smith", role_mention="from")]
        ),
    )


def _confidentiality_draft() -> ConstraintDraft:
    return ConstraintDraft(
        source_span="Agent A can't know I have cancer",
        effect="deny",
        principal_mentions=["Agent A"],
        modality=Modality.KNOWLEDGE,
        object=PropositionObject(text="I have cancer"),
    )


def test_access_policy_ready_and_confirmed(
    migrated_db_session: Session,
) -> None:
    account = ensure_account_from_session(migrated_db_session)
    person = _person(migrated_db_session, "John Smith", "john@example.com")
    source = _source_account(migrated_db_session, account.id)
    _email_from(migrated_db_session, source.id, "john@example.com")

    service = _service(migrated_db_session, FakeParser([_access_draft()]))
    state = service.create_draft(
        account.id, "Agent A can't see emails from John Smith", "fake"
    )

    constraint = state.constraints[0]
    assert constraint.state is ConstraintStateName.READY
    assert constraint.resolved is not None
    assert constraint.resolved.participants[0].person_id == str(person.id)
    assert "Applies to all agents" in (constraint.preview or "")
    assert constraint.impact is not None
    assert constraint.impact.matching_emails == 1

    summaries = service.confirm(account.id, state.draft_id, None)

    assert len(summaries) == 1
    assert summaries[0].status == "active"
    assert summaries[0].policy_type == "access"


def test_ambiguous_person_requires_clarification(
    migrated_db_session: Session,
) -> None:
    account = ensure_account_from_session(migrated_db_session)
    first = _person(migrated_db_session, "John Smith", "john@acme.com")
    _person(migrated_db_session, "John Smith", "jsmith@gmail.com")

    service = _service(migrated_db_session, FakeParser([_access_draft()]))
    state = service.create_draft(
        account.id, "Agent A can't see emails from John Smith", "fake"
    )

    constraint = state.constraints[0]
    assert constraint.state is ConstraintStateName.NEEDS_CLARIFICATION
    assert constraint.clarification is not None
    assert len(constraint.clarification.options) == 3

    answered = service.answer(account.id, state.draft_id, 0, str(first.id))
    assert answered.constraints[0].state is ConstraintStateName.READY

    summaries = service.confirm(account.id, state.draft_id, None)
    assert summaries[0].status == "active"


def test_confidentiality_is_stored_but_not_enforced(
    migrated_db_session: Session,
) -> None:
    account = ensure_account_from_session(migrated_db_session)
    service = _service(
        migrated_db_session,
        FakeParser([_confidentiality_draft()], canonical="The user has cancer"),
    )
    state = service.create_draft(account.id, "Agent A can't know I have cancer", "fake")

    constraint = state.constraints[0]
    assert constraint.state is ConstraintStateName.READY
    assert "The user has cancer" in (constraint.preview or "")
    assert "Enforcement is not active yet" in (constraint.preview or "")

    summaries = service.confirm(account.id, state.draft_id, None)
    assert summaries[0].status == "pending_enforcement"

    build = migrated_db_session.scalar(select(PolicyBuildModel))
    assert build is not None
    assert build.status == "pending_enforcement"

    statement = migrated_db_session.scalar(select(ProtectedStatementModel))
    assert statement is not None
    assert "cancer" not in statement.canonical_encrypted


def test_nothing_is_persisted_before_confirmation(
    migrated_db_session: Session,
) -> None:
    account = ensure_account_from_session(migrated_db_session)
    service = _service(migrated_db_session, FakeParser([_access_draft()]))

    service.create_draft(account.id, "Agent A can't see emails from John Smith", "fake")

    assert migrated_db_session.scalar(select(PolicyModel)) is None
    assert migrated_db_session.scalar(select(PolicyRevisionModel)) is None
    assert migrated_db_session.scalar(select(PolicyEventModel)) is None


def test_source_prompt_is_encrypted_and_audited(
    migrated_db_session: Session,
) -> None:
    account = ensure_account_from_session(migrated_db_session)
    _person(migrated_db_session, "John Smith", "john@example.com")
    service = _service(migrated_db_session, FakeParser([_access_draft()]))
    state = service.create_draft(
        account.id, "Agent A can't see emails from John Smith", "fake"
    )
    service.confirm(account.id, state.draft_id, None)

    revision = migrated_db_session.scalar(select(PolicyRevisionModel))
    assert revision is not None
    assert "can't see emails" not in revision.source_encrypted
    assert "can't see emails" in decrypt_secret(revision.source_encrypted)

    event = migrated_db_session.scalar(select(PolicyEventModel))
    assert event is not None
    assert event.event == "created"
    assert "can't see emails" not in event.interpreter_version


def ensure_account_from_session(session: Session):
    from rosalind.adapters.outbound.persistence.unit_of_work import (
        SqlAlchemyUnitOfWork,
    )

    return ensure_account(SqlAlchemyUnitOfWork(session))
