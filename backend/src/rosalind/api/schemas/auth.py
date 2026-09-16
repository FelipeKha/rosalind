"""Request and response schemas for provider authentication endpoints."""

import uuid

from pydantic import BaseModel


class ConnectResponse(BaseModel):
    auth_url: str
    state: str


class AuthStatusResponse(BaseModel):
    status: str
    source_account_id: uuid.UUID | None = None
    display_name: str | None = None
