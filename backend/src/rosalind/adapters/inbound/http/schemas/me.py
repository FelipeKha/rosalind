"""Schemas for the current-account profile endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AccountProfileResponse(BaseModel):
    account_id: uuid.UUID
    self_person_id: uuid.UUID | None = None
    created_at: datetime
    subject: str
    email: str | None = None
    preferred_username: str | None = None
    given_name: str | None = None
    family_name: str | None = None


class SetSelfPersonRequest(BaseModel):
    person_id: uuid.UUID


class SetSelfPersonResponse(BaseModel):
    self_person_id: uuid.UUID
