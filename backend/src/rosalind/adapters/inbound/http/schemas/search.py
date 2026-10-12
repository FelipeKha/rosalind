"""Request and response schemas for the email ``search`` endpoint.

Deliberately separate from the MCP schemas (``adapters.inbound.mcp``): REST is
consumed by software, MCP by an AI application, and their contracts may diverge
over time.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchFilters(BaseModel):
    """Lists are OR within a field; different fields are AND."""

    model_config = ConfigDict(extra="forbid")

    sender: list[str] | None = None
    recipient: list[str] | None = None
    participant: list[str] | None = None
    direction: Literal["received", "sent", "self", "unknown"] | None = None
    date_from: date | None = None
    date_before: date | None = None
    tags: list[str] | None = None
    exclude_tags: list[str] | None = None
    has_attachment: bool | None = None
    thread_of: uuid.UUID | None = None
    language: list[str] | None = None
    source_accounts: list[uuid.UUID] | None = None
    include_trash_spam: bool = False


class SearchEmailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    keywords: str | None = None
    filters: SearchFilters = SearchFilters()
    sort: Literal["relevance", "date_desc", "date_asc"] | None = None
    group_by: Literal["message", "thread"] = "message"
    view: Literal["metadata", "snippet"] = "snippet"
    limit: Annotated[int, Field(ge=1, le=25)] = 10
    cursor: str | None = None
    mode: Literal["hybrid", "lexical", "semantic"] = "hybrid"


class SearchWarning(BaseModel):
    code: str
    message: str
    field_name: str | None = None
    suggestion: str | None = None


class SearchCitation(BaseModel):
    item_id: uuid.UUID
    chunk_id: uuid.UUID
    thread_id: uuid.UUID | None = None


class SearchResultItem(BaseModel):
    item_id: uuid.UUID
    thread_id: uuid.UUID | None = None
    chunk_id: uuid.UUID
    subject: str | None = None
    sender: str
    date: datetime
    snippet: str | None = None
    matched_in: str  # "body" | "attachment"
    score: float | None = None
    citation: SearchCitation


class SearchResultResponse(BaseModel):
    request_id: uuid.UUID
    audit_id: uuid.UUID
    mode_requested: str | None = None
    mode_effective: str | None = None
    fingerprint: str | None = None
    short_circuit: str | None = None
    explanation: str | None = None
    applied_filters: dict = Field(default_factory=dict)
    warnings: list[SearchWarning] = Field(default_factory=list)
    results: list[SearchResultItem] = Field(default_factory=list)
    total_estimate: int | None = None
    next_cursor: str | None = None
