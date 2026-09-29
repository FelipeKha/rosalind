"""Keycloak bearer-token verifier using local JWKS validation.

Validates a JWT against the realm's public keys fetched from Keycloak's JWKS
endpoint, pinning the expected issuer and audience. This is the concrete
``TokenVerifier`` implementation behind both the REST and MCP adapters.
"""

from __future__ import annotations

import jwt
from jwt import PyJWKClient, PyJWKClientError

from rosalind import config
from rosalind.application.ports.identity import TokenVerifier, VerifiedToken

_ALGORITHMS = ["RS256"]


class KeycloakJwtVerifier:
    """Validate Keycloak-issued JWTs locally against the realm JWKS."""

    def __init__(self) -> None:
        settings = config.settings
        realm_base = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        self._issuer = realm_base
        self._audience = settings.keycloak_audience
        self._jwks = PyJWKClient(f"{realm_base}/protocol/openid-connect/certs")

    def verify(self, token: str) -> VerifiedToken | None:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
        except PyJWKClientError:
            return None

        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=_ALGORITHMS,
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["iss", "sub", "exp", "aud"]},
            )
        except jwt.PyJWTError:
            return None

        subject = claims.get("sub")
        if not subject:
            return None

        scope = claims.get("scope")
        return VerifiedToken(
            issuer=self._issuer,
            subject=subject,
            client_id=claims.get("azp") or claims.get("client_id"),
            scopes=scope.split() if isinstance(scope, str) else None,
        )


token_verifier: TokenVerifier = KeycloakJwtVerifier()
