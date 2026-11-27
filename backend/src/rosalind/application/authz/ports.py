"""Ports used by the access-enforcement application layer."""

from __future__ import annotations

import uuid
from typing import Protocol

from rosalind.application.authz.models import LoadedAccessPolicies


class AccessPolicyRepository(Protocol):
    """Load the active access-policy snapshot for one account.

    Implementations must fail closed by raising; the application layer turns a
    failure into an empty/deny-all response and records a security event.
    """

    async def load_access_policies(
        self, account_id: uuid.UUID
    ) -> LoadedAccessPolicies: ...


class SecurityEventPort(Protocol):
    """Record a content-free security event (L2 failure, load failure, etc.)."""

    async def record(
        self,
        *,
        account_id: uuid.UUID | None,
        request_id: uuid.UUID | None,
        event: str,
        detail: dict[str, object] | None = None,
    ) -> None: ...


__all__ = ["AccessPolicyRepository", "SecurityEventPort"]
