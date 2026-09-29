"""Request and response schemas for import and processing endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FileEntryRequest(BaseModel):
    path: str
    sha256: str
    size: int = Field(ge=0)
    format: str | None = None
    modified_at: datetime | None = None


class ManifestRequest(BaseModel):
    files: list[FileEntryRequest]


class ImportCreateRequest(BaseModel):
    source_name: str
    type: str


class ImportCreatedResponse(BaseModel):
    import_id: uuid.UUID
    source_id: uuid.UUID | None = None
    source_name: str | None = None
    type: str
    bucket: str
    storage_prefix: str
    ingestion_status: str
    processing_status: str


class FileResponse(BaseModel):
    path: str
    sha256: str
    size: int
    format: str | None = None
    modified_at: datetime | None = None
    storage_key: str


class ImportSummaryResponse(BaseModel):
    import_id: uuid.UUID
    source_id: uuid.UUID | None = None
    source_name: str | None = None
    type: str
    ingestion_status: str
    processing_status: str
    created_at: datetime
    completed_at: datetime | None = None
    file_count: int
    total_size: int
    import_hash: str | None = None


class ImportListResponse(BaseModel):
    imports: list[ImportSummaryResponse]


class ImportDetailResponse(ImportSummaryResponse):
    files: list[FileResponse]


class ProcessingResultResponse(BaseModel):
    import_id: uuid.UUID
    processing_status: str
    result: str
    message: str | None = None
    people_created: int = 0
    facts_created: int = 0
    facts_reused: int = 0
    assertions_created: int = 0
