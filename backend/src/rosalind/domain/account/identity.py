"""Account identity domain entity.

An account identity binds a Rosalind ``Account`` to an identity asserted by an
external identity provider. ``issuer`` is the provider's issuer identifier and
``subject`` is the provider-scoped subject claim; together they are unique, so
the same user authenticating through the same provider resolves to the same
account.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AccountIdentity:
    id: uuid.UUID
    account_id: uuid.UUID
    issuer: str
    subject: str
    created_at: datetime
    last_seen_at: datetime
