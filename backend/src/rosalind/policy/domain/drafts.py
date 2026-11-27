"""Draft state, resolution and public policy read models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rosalind.policy.domain.extraction import ConstraintDraft


class ConstraintStateName(StrEnum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"
    CONFIRMED = "confirmed"


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    detail: str | None = None


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_code: str
    text: str
    options: list[ClarificationOption]
    field: str
    round: int = 1
    max_rounds: int = 2


class ImpactReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matching_emails: int | None = None
    matching_addresses: int | None = None
    note: str | None = None


class ResolvedParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mention: str
    roles: list[str]
    person_id: str | None = None
    addresses: list[str] = Field(default_factory=list)
    matched_by: str


class ResolvedConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["access", "confidentiality"]
    effect: Literal["permit", "deny"]
    participants: list[ResolvedParticipant] = Field(default_factory=list)
    account_id: str | None = None
    account_label: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    direction: Literal["received", "sent"] | None = None
    statement: str | None = None
    statement_kind: Literal["fact", "topic"] | None = None
    assumptions: list[str] = Field(default_factory=list)
    resolution_notes: list[str] = Field(default_factory=list)


class ConstraintState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    state: ConstraintStateName
    kind: Literal["access", "confidentiality"] | None = None
    draft: ConstraintDraft | None = None
    resolved: ResolvedConstraint | None = None
    spec: dict[str, Any] | None = None
    preview: str | None = None
    impact: ImpactReport | None = None
    conflicts: list[str] = Field(default_factory=list)
    unsupported_parts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    resolution_notes: list[str] = Field(default_factory=list)
    clarification: ClarificationRequest | None = None
    overrides: dict[str, str] = Field(default_factory=dict)
    policy: PolicySummary | None = None
    error: str | None = None


class PolicySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: uuid.UUID
    revision: int
    policy_type: Literal["access", "confidentiality"]
    principal_kind: str
    status: str
    title: str


class DraftState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: uuid.UUID
    expires_at: datetime
    model: str
    interpreter_version: str
    constraints: list[ConstraintState]


class DraftPayload(BaseModel):
    """Encrypted-at-rest draft payload. Never persisted in plaintext."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    model: str
    model_id: str
    interpreter_version: str
    constraints: list[ConstraintState]

    def to_state(self, draft_id: uuid.UUID, expires_at: datetime) -> DraftState:
        return DraftState(
            draft_id=draft_id,
            expires_at=expires_at,
            model=self.model,
            interpreter_version=self.interpreter_version,
            constraints=self.constraints,
        )


class PolicySource(BaseModel):
    """Encrypted-at-rest provenance block for a revision."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["natural_language"] = "natural_language"
    prompt: str
    language: str = "en"
    confirmed_description: str
    interpreter_version: str
    model_id: str
    confirmed_at: datetime


class PolicyDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: uuid.UUID
    revision: int
    policy_type: str
    principal_kind: str
    status: str
    spec: dict[str, Any]
    source: PolicySource | None = None
    created_at: datetime


# PolicySummary is referenced before its definition inside ConstraintState; the
# forward reference is resolved once the module is fully loaded.
ConstraintState.model_rebuild()
