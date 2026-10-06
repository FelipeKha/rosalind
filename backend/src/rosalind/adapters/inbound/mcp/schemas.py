"""MCP-facing response models.

Deliberately separate from the REST schemas: MCP is consumed by an AI
application, not a software developer, so its contract may diverge over time
(e.g. exposing birth_year/month/day as a single ``birth_date``). Keeping the
two boundaries independent avoids one constraining the other.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class PersonProfileResult(BaseModel):
    person_id: uuid.UUID
    display_name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    primary_email: str | None = None
    email_verified: bool | None = None
    gender: str | None = None
    locale: str | None = None
    birth_year: int | None = None
    birth_month: int | None = None
    birth_day: int | None = None


class MyProfileResult(BaseModel):
    account_id: uuid.UUID
    self_person_id: uuid.UUID | None = None
    email: str | None = None
    preferred_username: str | None = None
    given_name: str | None = None
    family_name: str | None = None


class SearchWarning(BaseModel):
    code: str
    message: str
    field_name: str | None = None
    suggestion: str | None = None


class SearchResult(BaseModel):
    """The ``search`` tool response.

    Retrieval, fusion, rerank, and assembly are later phases, so ``results`` is
    empty for now; a successful Prepare echoes the applied filters and warnings
    so the agent can see how its request was interpreted.
    """

    request_id: uuid.UUID
    audit_id: uuid.UUID
    mode_requested: str | None = None
    mode_effective: str | None = None
    fingerprint: str | None = None
    short_circuit: str | None = None
    explanation: str | None = None
    applied_filters: dict = Field(default_factory=dict)
    warnings: list[SearchWarning] = Field(default_factory=list)
    results: list[dict] = Field(default_factory=list)
    next_cursor: str | None = None
