"""Request and response schemas for source endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SourceCreateRequest(BaseModel):
    provider: str
    name: str


class SourceConnectRequest(BaseModel):
    provider: str
    name: str | None = None


class ConnectResponse(BaseModel):
    source_id: uuid.UUID
    auth_url: str
    state: str


class ConnectStatusResponse(BaseModel):
    status: str
    source_id: uuid.UUID | None = None
    display_name: str | None = None


class DisconnectResponse(BaseModel):
    status: str
    revoked: bool


class SourceSummaryResponse(BaseModel):
    source_id: uuid.UUID
    name: str | None = None
    provider: str
    display_name: str | None = None
    status: str
    created_at: datetime


class SourceDetailResponse(SourceSummaryResponse):
    account_identifier: str | None = None


class SourceListResponse(BaseModel):
    sources: list[SourceSummaryResponse]
