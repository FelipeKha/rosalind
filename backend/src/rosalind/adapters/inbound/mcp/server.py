"""MCP adapter exposing the person read model.

A peer of the REST API: it calls the same ``PersonService``, just translating
MCP tool calls instead of HTTP requests. It reuses the backend's single
``SessionLocal`` / config path so there is exactly one connection construction.
"""

from __future__ import annotations

import uuid

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl

from rosalind import config
from rosalind.adapters import composition
from rosalind.adapters.inbound.mcp.schemas import (
    MyProfileResult,
    PersonProfileResult,
    SearchResult,
)
from rosalind.adapters.inbound.mcp.search import (
    SearchEmailsInput,
    to_search_request,
    to_search_result,
    to_short_circuit_result,
)
from rosalind.adapters.inbound.mcp.verifier import KeycloakMCPTokenVerifier
from rosalind.adapters.outbound.persistence.session import SessionLocal
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application.read_models import (
    CurrentAccount,
    PersonProfile,
    current_account_from,
)
from rosalind.application.search import ShortCircuit
from rosalind.application.services.search import PrepareContext


def _auth_settings() -> AuthSettings:
    settings = config.settings
    return AuthSettings(
        issuer_url=AnyHttpUrl(
            f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        ),
        resource_server_url=AnyHttpUrl(
            f"http://{settings.mcp_host}:{settings.mcp_port}"
        ),
        required_scopes=[],
        validate_token_resource=False,
    )


mcp = MCPServer(
    "rosalind",
    token_verifier=KeycloakMCPTokenVerifier(composition.token_verifier),
    auth=_auth_settings(),
)


@mcp.tool()
async def search(input: SearchEmailsInput) -> SearchResult | None:
    """Search the user's email archive.

    Filters are ANDed across fields; lists within a field are ORed. Prepare
    validates and normalizes the request into a search plan (or a short circuit
    when nothing can match); the ranked or list strategy then retrieves, fuses,
    reranks, and assembles a bounded page of results.
    """
    auth = _auth_context()
    if auth is None:
        return None
    account_id, client_id, zoneinfo = auth
    request = to_search_request(input)
    service = composition.build_search_service(SessionLocal)
    context = PrepareContext(
        account_id=account_id, client_id=client_id, timezone=zoneinfo
    )
    prepared = await service.prepare(context, request)
    if isinstance(prepared, ShortCircuit):
        return to_short_circuit_result(prepared)
    response = await service.search(prepared)
    return to_search_result(prepared, response)


@mcp.tool()
def search_people(query: str) -> list[PersonProfileResult]:
    """Search the user's known people by name or email address.

    Use this to identify a person in Rosalind. Returns people whose display
    name or primary email contains the query. This is a person lookup, not a
    general personal-data search.
    """
    account_id = _current_account_id()
    if account_id is None:
        return []
    with SessionLocal() as session:
        results = composition.build_person_service(session).search_people(
            account_id, query
        )
    return [_to_result(profile) for profile in results]


@mcp.tool()
def get_person(person_id: uuid.UUID) -> PersonProfileResult | None:
    """Retrieve the canonical profile of a specific person.

    Use this after identifying a person with search_people. Returns None if no
    such person exists.
    """
    account_id = _current_account_id()
    if account_id is None:
        return None
    with SessionLocal() as session:
        profile = composition.build_person_service(session).get_person(
            account_id, person_id
        )
    return _to_result(profile) if profile is not None else None


def _current_account_id() -> uuid.UUID | None:
    """Resolve the authenticated account id from the request token, if any.

    Returns None when no token is present (e.g. the local stdio transport),
    which leaves the read-only person tools with no account to scope to.
    """
    auth = _auth_context()
    return auth[0] if auth is not None else None


def _auth_context() -> tuple[uuid.UUID, str, str | None] | None:
    """Resolve the authenticated account plus the token's client and timezone.

    Returns ``(account_id, client_id, zoneinfo)`` or ``None`` when no token is
    present. The account is provisioned just-in-time, keyed only by ``(iss, sub)``.
    """
    token = get_access_token()
    if token is None or token.subject is None or token.claims is None:
        return None

    issuer = token.claims.get("iss") or ""
    with SessionLocal() as session:
        uow = SqlAlchemyUnitOfWork(session)
        account = composition.account_service.get_or_create(uow, issuer, token.subject)
        uow.commit()
        return (
            account.id,
            token.client_id or "unknown",
            token.claims.get("zoneinfo"),
        )


@mcp.tool()
def get_my_profile() -> MyProfileResult | None:
    """Return the authenticated user's Rosalind account and profile.

    Resolves the account from the current request's bearer token, so it
    requires an authenticated (HTTP) transport. Returns None when no token is
    present (e.g. the local stdio transport).
    """
    token = get_access_token()
    if token is None or token.subject is None or token.claims is None:
        return None

    issuer = token.claims.get("iss") or ""
    with SessionLocal() as session:
        uow = SqlAlchemyUnitOfWork(session)
        account = composition.account_service.get_or_create(uow, issuer, token.subject)
        uow.commit()
        profile = current_account_from(
            account,
            subject=token.subject,
            email=token.claims.get("email"),
            preferred_username=token.claims.get("preferred_username"),
            given_name=token.claims.get("given_name"),
            family_name=token.claims.get("family_name"),
        )
    return _to_profile_result(profile)


def _to_profile_result(profile: CurrentAccount) -> MyProfileResult:
    return MyProfileResult(
        account_id=profile.account_id,
        self_person_id=profile.self_person_id,
        email=profile.email,
        preferred_username=profile.preferred_username,
        given_name=profile.given_name,
        family_name=profile.family_name,
    )


def _to_result(profile: PersonProfile) -> PersonProfileResult:
    return PersonProfileResult(
        person_id=profile.person_id,
        display_name=profile.display_name,
        given_name=profile.given_name,
        family_name=profile.family_name,
        primary_email=profile.primary_email,
        email_verified=profile.email_verified,
        gender=profile.gender,
        locale=profile.locale,
        birth_year=profile.birth_year,
        birth_month=profile.birth_month,
        birth_day=profile.birth_day,
    )


def main() -> None:
    if config.settings.mcp_transport == "streamable-http":
        mcp.run(
            "streamable-http",
            host=config.settings.mcp_host,
            port=config.settings.mcp_port,
        )
    elif config.settings.mcp_transport == "sse":
        mcp.run("sse", host=config.settings.mcp_host, port=config.settings.mcp_port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
