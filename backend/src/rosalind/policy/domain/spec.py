"""Canonical policy specification (Phase 1 subset of ``rosalind.policy.v2``).

The Phase 1 model is deliberately narrow:

* principals are generic (``all_agents``); agent-specific scoping comes later;
* access selectors use exact, SQL-decidable predicates;
* confidentiality rules store a protected statement but are not enforced yet.

The ``source`` block is *not* part of the evaluated spec. It is stored
separately, encrypted, on the revision so prompt text never leaks into the
JSONB spec.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

SCHEMA_VERSION = "rosalind.policy.v2"


class Effect(StrEnum):
    PERMIT = "permit"
    DENY = "deny"


class PolicyType(StrEnum):
    ACCESS = "access"
    CONFIDENTIALITY = "confidentiality"


class PolicyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    BUILDING = "building"
    PENDING_ENFORCEMENT = "pending_enforcement"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    PAUSED = "paused"
    REVOKED = "revoked"


class PrincipalType(StrEnum):
    ALL_AGENTS = "all_agents"
    AGENT = "agent"


class Action(StrEnum):
    EMAIL_SEARCH = "email.search"
    EMAIL_READ_CONTENT = "email.read_content"
    EMAIL_READ_ATTACHMENT = "email.read_attachment"
    EMAIL_READ_EXTRACTION = "email.read_extraction"


DEFAULT_ACTIONS = [
    Action.EMAIL_SEARCH,
    Action.EMAIL_READ_CONTENT,
    Action.EMAIL_READ_ATTACHMENT,
    Action.EMAIL_READ_EXTRACTION,
]


class Role(StrEnum):
    FROM = "from"
    TO = "to"
    CC = "cc"
    BCC = "bcc"


class MatchLevel(StrEnum):
    ASSERTS = "asserts"
    IMPLIES = "implies"
    EVIDENCE = "evidence"


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: PrincipalType
    id: str | None = None

    @model_validator(mode="after")
    def _validate_id(self) -> Principal:
        if self.type is PrincipalType.AGENT and not self.id:
            raise ValueError("agent principal requires an id")
        if self.type is PrincipalType.ALL_AGENTS and self.id is not None:
            raise ValueError("all_agents principal must not set an id")
        return self


class HasParticipantPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Literal["has_participant"] = "has_participant"
    roles: list[Role] = Field(default_factory=lambda: list(Role))
    addresses: list[str] = Field(default_factory=list)
    person_id: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> HasParticipantPredicate:
        if not self.addresses and not self.person_id:
            raise ValueError("has_participant requires addresses or a person_id")
        return self


class InAccountPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Literal["in_account"] = "in_account"
    source_account_id: str


class DateRangePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operator: Literal["date_range"] = "date_range"
    from_date: date | None = Field(default=None, alias="from")
    to: date | None = None

    @model_validator(mode="after")
    def _validate(self) -> DateRangePredicate:
        if (
            self.from_date is not None
            and self.to is not None
            and self.from_date > self.to
        ):
            raise ValueError("date range start must not be after its end")
        if self.from_date is None and self.to is None:
            raise ValueError("date_range requires at least one bound")
        return self


class DirectionPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Literal["direction"] = "direction"
    direction: Literal["received", "sent"]


SelectorPredicate = Annotated[
    HasParticipantPredicate
    | InAccountPredicate
    | DateRangePredicate
    | DirectionPredicate,
    Field(discriminator="operator"),
]


class Selector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Literal["all_of"] = "all_of"
    predicates: list[SelectorPredicate] = Field(min_length=1)


class EmailResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["email"] = "email"
    selector: Selector


class ProtectedInformationResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["protected_information"] = "protected_information"
    kind: Literal["fact", "topic"]
    statement: str = Field(min_length=1)
    statement_id: str | None = None
    match_levels: list[MatchLevel] = Field(
        default_factory=lambda: [
            MatchLevel.ASSERTS,
            MatchLevel.IMPLIES,
            MatchLevel.EVIDENCE,
        ]
    )


class Treatment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["redact_span"] = "redact_span"
    fallback: Literal["drop_segment"] = "drop_segment"


class Enforcement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hold_until_ready: bool = False


class AccessPolicySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["rosalind.policy.v2"] = "rosalind.policy.v2"
    type: Literal["access"] = "access"
    effect: Effect
    principal: Principal
    actions: list[Action] = Field(default_factory=lambda: list(DEFAULT_ACTIONS))
    resource: EmailResource
    status: PolicyStatus


class ConfidentialityPolicySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["rosalind.policy.v2"] = "rosalind.policy.v2"
    type: Literal["confidentiality"] = "confidentiality"
    effect: Effect = Effect.DENY
    principal: Principal
    actions: list[Action] = Field(default_factory=lambda: list(DEFAULT_ACTIONS))
    resource: ProtectedInformationResource
    treatment: Treatment = Field(default_factory=Treatment)
    enforcement: Enforcement = Field(default_factory=Enforcement)
    status: PolicyStatus


PolicySpec = Annotated[
    AccessPolicySpec | ConfidentialityPolicySpec,
    Field(discriminator="type"),
]

PolicySpecAdapter: TypeAdapter[AccessPolicySpec | ConfidentialityPolicySpec] = (
    TypeAdapter(PolicySpec)
)


def validate_spec(data: object) -> AccessPolicySpec | ConfidentialityPolicySpec:
    """Validate an untyped spec payload from storage or the LLM boundary."""
    return PolicySpecAdapter.validate_python(data)
