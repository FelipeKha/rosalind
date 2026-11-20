"""Ports the policy application needs from the outside world."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from rosalind.config import ParserModelSettings
from rosalind.policy.domain.drafts import (
    PolicyDetail,
    PolicySource,
    PolicySummary,
)
from rosalind.policy.domain.extraction import CanonicalStatement, ExtractionResult


@dataclass(frozen=True)
class AccountRef:
    id: uuid.UUID
    self_person_id: uuid.UUID | None


@dataclass(frozen=True)
class PersonCandidate:
    person_id: uuid.UUID
    display_name: str
    addresses: list[str]


@dataclass(frozen=True)
class SourceAccountRef:
    id: uuid.UUID
    name: str
    display_name: str | None


@dataclass(frozen=True)
class DraftRecord:
    draft_id: uuid.UUID
    payload_encrypted: str
    expires_at: datetime


@dataclass(frozen=True)
class NewPolicy:
    account_id: uuid.UUID
    title: str
    policy_type: str
    principal_kind: str
    status: str
    spec: dict[str, object]
    source: PolicySource
    statement: str | None
    statement_kind: str | None
    interpreter_version: str
    model_id: str


class PromptParser(Protocol):
    @property
    def model_name(self) -> str: ...

    def extract(self, prompt: str) -> ExtractionResult: ...

    def canonicalize(self, text: str, kind: str) -> CanonicalStatement: ...


class ParserFactory(Protocol):
    def __call__(self, model: ParserModelSettings) -> PromptParser: ...


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


class SecretBox(Protocol):
    def encrypt(self, value: str) -> str: ...

    def decrypt(self, token: str) -> str: ...


class PolicyRepository(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    # accounts / directory (read-only for the policy service)
    def get_or_create_account(self, issuer: str, subject: str) -> AccountRef: ...

    def self_person_id(self, account_id: uuid.UUID) -> uuid.UUID | None: ...

    def find_people(self, mention: str) -> list[PersonCandidate]: ...

    def get_person(self, person_id: uuid.UUID) -> PersonCandidate | None: ...

    def find_source_accounts(
        self, account_id: uuid.UUID, mention: str
    ) -> list[SourceAccountRef]: ...

    def get_source_account(
        self, account_id: uuid.UUID, source_account_id: uuid.UUID
    ) -> SourceAccountRef | None: ...

    def count_participant_emails(
        self, account_id: uuid.UUID, addresses: list[str]
    ) -> int: ...

    # drafts
    def create_draft(
        self, account_id: uuid.UUID, payload_encrypted: str, expires_at: datetime
    ) -> DraftRecord: ...

    def get_draft(
        self, account_id: uuid.UUID, draft_id: uuid.UUID
    ) -> DraftRecord | None: ...

    def update_draft(
        self,
        account_id: uuid.UUID,
        draft_id: uuid.UUID,
        payload_encrypted: str,
        expires_at: datetime,
    ) -> None: ...

    def delete_draft(self, account_id: uuid.UUID, draft_id: uuid.UUID) -> None: ...

    def delete_expired_drafts(self, now: datetime) -> int: ...

    # policies
    def create_policy(self, policy: NewPolicy) -> PolicySummary: ...

    def list_policies(self, account_id: uuid.UUID) -> list[PolicySummary]: ...

    def get_policy(
        self, account_id: uuid.UUID, policy_id: uuid.UUID
    ) -> PolicyDetail | None: ...

    def set_policy_status(
        self, account_id: uuid.UUID, policy_id: uuid.UUID, status: str
    ) -> PolicySummary | None: ...
