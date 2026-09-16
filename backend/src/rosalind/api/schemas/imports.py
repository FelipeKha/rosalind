"""Request and response schemas for import endpoints."""

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


class ImportCreatedResponse(BaseModel):
    import_id: uuid.UUID
    bucket: str
    storage_prefix: str
    status: str


class FileResponse(BaseModel):
    path: str
    sha256: str
    size: int
    format: str | None = None
    modified_at: datetime | None = None
    storage_key: str


class ImportSummaryResponse(BaseModel):
    import_id: uuid.UUID
    source: str
    type: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    file_count: int
    total_size: int
    import_hash: str | None = None


class ImportListResponse(BaseModel):
    imports: list[ImportSummaryResponse]


class ImportDetailResponse(ImportSummaryResponse):
    files: list[FileResponse]


class GoogleProfileImportResponse(BaseModel):
    status: str
    account: str | None = None
    display_name: str | None = None
    fetched_at: datetime
