"""Request and response schemas for import and processing endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class FileEntryRequest(BaseModel):
    path: str
    sha256: str
    size: int = Field(ge=0)
    format: str | None = None
    modified_at: datetime | None = None


class ManifestRequest(BaseModel):
    files: list[FileEntryRequest]


class ImportCreateRequest(BaseModel):
    source_name: Literal["google", "none"] = "none"
    via: Literal["file", "api"] = "file"

    @model_validator(mode="after")
    def _check_combination(self) -> Self:
        if self.via == "api" and self.source_name != "google":
            raise ValueError("via='api' requires source_name='google'")
        return self


class ImportCreatedResponse(BaseModel):
    import_id: uuid.UUID
    source_id: uuid.UUID | None = None
    source_name: str | None = None
    via: str
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
    via: str
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
