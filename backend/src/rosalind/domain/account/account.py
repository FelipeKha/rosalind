"""Rosalind account domain entity.

An account is Rosalind's own concept of a user. It is deliberately distinct
from ``AccountIdentity`` (an authentication-provider notion): one account may
be reached through many identities across different identity providers, and
``self_person_id`` optionally links the account to the canonical person that
represents its owner.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    self_person_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
