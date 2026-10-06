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
from rosalind.adapters.inbound.mcp.schemas import MyProfileResult, PersonProfileResult
from rosalind.adapters.inbound.mcp.search import SearchEmailsInput, to_search_request
from rosalind.adapters.inbound.mcp.verifier import KeycloakMCPTokenVerifier
from rosalind.adapters.outbound.persistence.session import SessionLocal
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application.read_models import (
    CurrentAccount,
    PersonProfile,
    current_account_from,
)


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
def search(input: SearchEmailsInput) -> object:
    """Search the user's email archive.

    Filters are ANDed across fields; lists within a field are ORed. Phase 0
    registers the tool and its input contract only; the search itself is not
    implemented yet and raises a clear error until the Prepare phase lands.
    """
    account_id = _current_account_id()
    if account_id is None:
        return None
    request = to_search_request(input)
    return composition.search_service.prepare(account_id, request)


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
    token = get_access_token()
    if token is None or token.subject is None or token.claims is None:
        return None

    issuer = token.claims.get("iss") or ""
    with SessionLocal() as session:
        uow = SqlAlchemyUnitOfWork(session)
        account = composition.account_service.get_or_create(uow, issuer, token.subject)
        uow.commit()
        return account.id


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
