"""Constrained extraction contracts.

The local LLM returns an :class:`ExtractionResult`: one draft per atomic
constraint, with raw text mentions only. IDs, defaults, routing and preview
text are produced by deterministic code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class RoleMention(StrEnum):
    FROM = "from"
    TO = "to"
    CC = "cc"
    BCC = "bcc"
    ANY = "any"


class EffectMention(StrEnum):
    DENY = "deny"
    PERMIT = "permit"


class Modality(StrEnum):
    ACCESS = "access"
    KNOWLEDGE = "knowledge"


class ParticipantMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mention: str
    role_mention: RoleMention = RoleMention.ANY


class DateRangeMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mention: str


class EmailSelectorObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["email_selector"] = "email_selector"
    participants: list[ParticipantMention] = Field(default_factory=list)
    date_range: DateRangeMention | None = None
    account_mention: str | None = None
    direction: Literal["received", "sent"] | None = None


class PropositionObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["proposition"] = "proposition"
    text: str


class TopicObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["topic"] = "topic"
    text: str


class ContentClassObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["content_class"] = "content_class"
    text: str


ExtractionObject = Annotated[
    EmailSelectorObject | PropositionObject | TopicObject | ContentClassObject,
    Field(discriminator="type"),
]


class UnsupportedPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    reason: str


class ConstraintDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_span: str
    effect: EffectMention
    principal_mentions: list[str] = Field(default_factory=list)
    modality: Modality
    object: ExtractionObject
    unsupported_parts: list[UnsupportedPart] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraints: list[ConstraintDraft] = Field(default_factory=list)


class CanonicalStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    atomic: bool = True
    is_question_or_instruction: bool = False
