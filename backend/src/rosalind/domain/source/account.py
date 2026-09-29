"""Source account domain entity.

A source account is a connection to an external data holder (e.g. a Google
account). It has a human-facing ``name`` (the CLI slug) distinct from the
immutable provider identity (``provider`` + ``account_identifier``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceAccount:
    id: uuid.UUID
    provider: str
    name: str | None
    account_identifier: str | None
    display_name: str | None
    created_at: datetime
