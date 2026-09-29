"""MCP bearer-token verifier.

Adapts the shared ``TokenVerifier`` (Keycloak/JWKS) to the MCP SDK's
``TokenVerifier`` protocol so the MCP server uses the same validation path as
the REST API.
"""

from __future__ import annotations

from mcp.server.auth.provider import AccessToken

from rosalind.application.ports.identity import TokenVerifier


class KeycloakMCPTokenVerifier:
    def __init__(self, verifier: TokenVerifier):
        self._verifier = verifier

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = self._verifier.verify(token)
        if verified is None:
            return None
        return AccessToken(
            token=token,
            client_id=verified.client_id or "unknown",
            scopes=verified.scopes or [],
            subject=verified.subject,
            claims={
                "iss": verified.issuer,
                "email": verified.email,
                "preferred_username": verified.preferred_username,
                "given_name": verified.given_name,
                "family_name": verified.family_name,
            },
        )
