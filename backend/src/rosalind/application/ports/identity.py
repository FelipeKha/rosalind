"""Identity verification port (bearer-token validation).

The application layer needs to turn a bearer token into the authenticated
identity's ``issuer`` + ``subject`` without knowing how tokens are validated.
Concrete implementations (e.g. a Keycloak/JWKS verifier) live in
``adapters.outbound``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VerifiedToken:
    """A successfully validated bearer token's identity claims."""

    issuer: str
    subject: str
    client_id: str | None = None
    scopes: list[str] | None = None
    email: str | None = None
    preferred_username: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    zoneinfo: str | None = None


class TokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedToken | None:
        """Validate a bearer token and return its identity, or ``None``."""
