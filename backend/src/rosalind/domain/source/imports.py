"""Import domain entities.

An import is a discrete ingestion job/dataset bound to a source account. It
tracks two independent dimensions: ``ingestion_status`` (was the data brought
in?) and ``processing_status`` (has it been turned into canonical data?).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ImportFile:
    path: str
    sha256: str
    size: int
    format: str | None
    modified_at: datetime | None
    storage_key: str


@dataclass(frozen=True)
class Import:
    id: uuid.UUID
    source_account_id: uuid.UUID | None
    source_name: str | None
    type: str
    ingestion_status: str
    processing_status: str
    created_at: datetime
    completed_at: datetime | None
    file_count: int
    total_size: int
    import_hash: str | None
    files: tuple[ImportFile, ...] = ()
