from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from rosalind.config import ParserModelSettings, PolicySettings
from rosalind.policy.application.interpreter import InterpreterService
from rosalind.policy.application.ports import (
    AccountRef,
    DraftRecord,
    NewPolicy,
    PersonCandidate,
    SourceAccountRef,
)
from rosalind.policy.domain.drafts import (
    ConstraintStateName,
    PolicyDetail,
    PolicySummary,
)
from rosalind.policy.domain.extraction import (
    CanonicalStatement,
    ConstraintDraft,
    DateRangeMention,
    EmailSelectorObject,
    ExtractionResult,
    Modality,
    ParticipantMention,
    PropositionObject,
)

SETTINGS = PolicySettings(
    models=[ParserModelSettings(name="fake", model="fake:latest")],
    default_model="fake",
)


class PlainBox:
    def encrypt(self, value: str) -> str:
        return value

    def decrypt(self, token: str) -> str:
        return token


class FakeRepository:
    def __init__(self) -> None:
        self.account_id = uuid.uuid4()
        self.people = [
            PersonCandidate(
                person_id=uuid.uuid4(),
                display_name="John Smith",
                addresses=["john@example.com"],
            )
        ]
        self.source_accounts = [
            SourceAccountRef(id=uuid.uuid4(), name="work", display_name="Work")
        ]
        self.drafts: dict[uuid.UUID, DraftRecord] = {}
        self.policies: dict[uuid.UUID, tuple[NewPolicy, PolicySummary]] = {}
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return

    def get_or_create_account(self, issuer: str, subject: str) -> AccountRef:
        del issuer, subject
        return AccountRef(id=self.account_id, self_person_id=None)

    def self_person_id(self, account_id: uuid.UUID) -> uuid.UUID | None:
        del account_id
        return None

    def find_people(self, mention: str) -> list[PersonCandidate]:
        normalized = mention.lower()
        return [
            person
            for person in self.people
            if normalized in person.display_name.lower()
            or normalized in person.addresses
        ]

    def get_person(self, person_id: uuid.UUID) -> PersonCandidate | None:
        return next(
            (person for person in self.people if person.person_id == person_id),
            None,
        )

    def find_source_accounts(
        self, account_id: uuid.UUID, mention: str
    ) -> list[SourceAccountRef]:
        del account_id
        normalized = mention.lower()
        return [
            account
            for account in self.source_accounts
            if normalized in account.name.lower()
            or (
                account.display_name is not None
                and normalized in account.display_name.lower()
            )
        ]

    def get_source_account(
        self, account_id: uuid.UUID, source_account_id: uuid.UUID
    ) -> SourceAccountRef | None:
        del account_id
        return next(
            (
                account
                for account in self.source_accounts
                if account.id == source_account_id
            ),
            None,
        )

    def count_participant_emails(
        self, account_id: uuid.UUID, addresses: list[str]
    ) -> int:
        del account_id, addresses
        return 42

    def create_draft(
        self, account_id: uuid.UUID, payload_encrypted: str, expires_at: datetime
    ) -> DraftRecord:
        del account_id
        draft = DraftRecord(
            draft_id=uuid.uuid4(),
            payload_encrypted=payload_encrypted,
            expires_at=expires_at,
        )
        self.drafts[draft.draft_id] = draft
        return draft

    def get_draft(
        self, account_id: uuid.UUID, draft_id: uuid.UUID
    ) -> DraftRecord | None:
        del account_id
        return self.drafts.get(draft_id)

    def update_draft(
        self,
        account_id: uuid.UUID,
        draft_id: uuid.UUID,
        payload_encrypted: str,
        expires_at: datetime,
    ) -> None:
        del account_id
        self.drafts[draft_id] = DraftRecord(
            draft_id=draft_id,
            payload_encrypted=payload_encrypted,
            expires_at=expires_at,
        )

    def delete_draft(self, account_id: uuid.UUID, draft_id: uuid.UUID) -> None:
        del account_id
        self.drafts.pop(draft_id, None)

    def delete_expired_drafts(self, now: datetime) -> int:
        expired = [
            draft_id
            for draft_id, draft in self.drafts.items()
            if draft.expires_at < now
        ]
        for draft_id in expired:
            del self.drafts[draft_id]
        return len(expired)

    def create_policy(self, policy: NewPolicy) -> PolicySummary:
        summary = PolicySummary(
            policy_id=uuid.uuid4(),
            revision=1,
            policy_type=policy.policy_type,  # type: ignore[arg-type]
            principal_kind=policy.principal_kind,
            status=policy.status,
            title=policy.title,
        )
        self.policies[summary.policy_id] = (policy, summary)
        return summary

    def list_policies(self, account_id: uuid.UUID) -> list[PolicySummary]:
        del account_id
        return [summary for _, summary in self.policies.values()]

    def get_policy(
        self, account_id: uuid.UUID, policy_id: uuid.UUID
    ) -> PolicyDetail | None:
        del account_id
        entry = self.policies.get(policy_id)
        if entry is None:
            return None
        policy, _ = entry
        return PolicyDetail(
            policy_id=policy_id,
            revision=1,
            policy_type=policy.policy_type,
            principal_kind=policy.principal_kind,
            status=policy.status,
            spec=policy.spec,
            source=policy.source,
            created_at=policy.source.confirmed_at,
        )

    def set_policy_status(
        self, account_id: uuid.UUID, policy_id: uuid.UUID, status: str
    ) -> PolicySummary | None:
        entry = self.get_policy(account_id, policy_id)
        if entry is None:
            return None
        policy, summary = self.policies[policy_id]
        updated = summary.model_copy(update={"status": status})
        self.policies[policy_id] = (policy, updated)
        return updated


class FakeParser:
    def __init__(
        self,
        constraints: list[ConstraintDraft],
        canonical: str = "The user has cancer",
    ) -> None:
        self._constraints = constraints
        self._canonical = canonical

    @property
    def model_name(self) -> str:
        return "fake"

    def extract(self, prompt: str) -> ExtractionResult:
        del prompt
        return ExtractionResult(constraints=self._constraints)

    def canonicalize(self, text: str, kind: str) -> CanonicalStatement:
        del text, kind
        return CanonicalStatement(text=self._canonical)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

    def today(self) -> date:
        return self.now().date()


def _service(repository: FakeRepository, parser: FakeParser) -> InterpreterService:
    return InterpreterService(
        repository=repository,
        parser_factory=lambda model: parser,
        secret_box=PlainBox(),
        settings=SETTINGS,
        clock=FixedClock(),
    )


def _access() -> ConstraintDraft:
    return ConstraintDraft(
        source_span="Agent A can't see emails from John Smith",
        effect="deny",
        principal_mentions=["Agent A"],
        modality=Modality.ACCESS,
        object=EmailSelectorObject(
            participants=[ParticipantMention(mention="John Smith", role_mention="from")]
        ),
    )


def _confidential() -> ConstraintDraft:
    return ConstraintDraft(
        source_span="Agent A can't know I have cancer",
        effect="deny",
        principal_mentions=["Agent A"],
        modality=Modality.KNOWLEDGE,
        object=PropositionObject(text="I have cancer"),
    )


def test_access_flow_ready_and_confirmed() -> None:
    repository = FakeRepository()
    service = _service(repository, FakeParser([_access()]))

    state = service.create_draft(
        repository.account_id,
        "Agent A can't see emails from John Smith",
        "fake",
    )

    constraint = state.constraints[0]
    assert constraint.state is ConstraintStateName.READY
    assert "Applies to all agents" in (constraint.preview or "")
    assert constraint.impact is not None
    assert constraint.impact.matching_emails == 42
    assert repository.policies == {}

    summaries = service.confirm(repository.account_id, state.draft_id, None)

    assert len(summaries) == 1
    assert summaries[0].status == "active"
    assert len(repository.policies) == 1


def test_confirmation_is_idempotent() -> None:
    repository = FakeRepository()
    service = _service(repository, FakeParser([_access()]))
    state = service.create_draft(
        repository.account_id,
        "Agent A can't see emails from John Smith",
        "fake",
    )

    first = service.confirm(repository.account_id, state.draft_id, None)
    second = service.confirm(repository.account_id, state.draft_id, None)

    assert first == second
    assert len(repository.policies) == 1


def test_ambiguous_person_clarification() -> None:
    repository = FakeRepository()
    repository.people.append(
        PersonCandidate(
            person_id=uuid.uuid4(),
            display_name="John Smith",
            addresses=["jsmith@gmail.com"],
        )
    )
    service = _service(repository, FakeParser([_access()]))

    state = service.create_draft(
        repository.account_id,
        "Agent A can't see emails from John Smith",
        "fake",
    )
    constraint = state.constraints[0]
    assert constraint.state is ConstraintStateName.NEEDS_CLARIFICATION
    assert constraint.clarification is not None
    assert len(constraint.clarification.options) == 3

    chosen = constraint.clarification.options[0]
    answered = service.answer(repository.account_id, state.draft_id, 0, chosen.id)
    assert answered.constraints[0].state is ConstraintStateName.READY


def test_confidentiality_is_pending_enforcement() -> None:
    repository = FakeRepository()
    service = _service(repository, FakeParser([_confidential()]))

    state = service.create_draft(
        repository.account_id,
        "Agent A can't know I have cancer",
        "fake",
    )
    constraint = state.constraints[0]
    assert constraint.state is ConstraintStateName.READY
    assert constraint.spec is not None
    assert constraint.spec["status"] == "pending_enforcement"
    assert "The user has cancer" in (constraint.preview or "")

    summaries = service.confirm(repository.account_id, state.draft_id, None)
    assert summaries[0].status == "pending_enforcement"


def test_span_must_appear_in_prompt() -> None:
    repository = FakeRepository()
    service = _service(repository, FakeParser([_access()]))

    state = service.create_draft(
        repository.account_id, "totally different prompt", "fake"
    )

    assert state.constraints[0].state is ConstraintStateName.UNSUPPORTED
    assert state.constraints[0].error == "extraction_failed"


def test_date_mention_is_frozen() -> None:
    repository = FakeRepository()
    draft = _access()
    draft.object = EmailSelectorObject(date_range=DateRangeMention(mention="last year"))
    draft.source_span = "Agent A can't see emails from last year"
    service = _service(repository, FakeParser([draft]))

    state = service.create_draft(
        repository.account_id,
        "Agent A can't see emails from last year",
        "fake",
    )
    resolved = state.constraints[0].resolved

    assert resolved is not None
    assert resolved.date_from == date(2025, 1, 1)
    assert resolved.date_to == date(2026, 1, 1)


def test_draft_expiry_uses_configured_ttl() -> None:
    repository = FakeRepository()
    service = _service(repository, FakeParser([_access()]))
    state = service.create_draft(
        repository.account_id,
        "Agent A can't see emails from John Smith",
        "fake",
    )

    assert state.expires_at - FixedClock().now() == timedelta(hours=1)
