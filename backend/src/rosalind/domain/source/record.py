"""Provider-independent raw source record value object.

A source record is an immutable observation of a provider object. It is the
application-facing view of ``raw.source_record``; the concrete SQLAlchemy model
lives in the persistence adapter and is never imported by the application layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRecord:
    """Immutable snapshot of a provider payload.

    Provider-specific metadata (etag, source timestamps) stays in the raw layer;
    only the fields the application needs to canonicalize are exposed here.
    """

    id: uuid.UUID
    source_account_id: uuid.UUID
    resource_type: str
    external_id: str
    payload: dict
    payload_sha256: str
