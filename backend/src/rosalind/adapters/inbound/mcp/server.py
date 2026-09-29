"""MCP adapter exposing the person read model.

A peer of the REST API: it calls the same ``PersonService``, just translating
MCP tool calls instead of HTTP requests. It reuses the backend's single
``SessionLocal`` / config path so there is exactly one connection construction.
"""

from __future__ import annotations

import uuid

from mcp.server.mcpserver import MCPServer

from rosalind import config
from rosalind.adapters import composition
from rosalind.adapters.inbound.mcp.schemas import PersonProfileResult
from rosalind.adapters.outbound.persistence.session import SessionLocal
from rosalind.application.read_models import PersonProfile

mcp = MCPServer("rosalind")


@mcp.tool()
def search_people(query: str) -> list[PersonProfileResult]:
    """Search the user's known people by name or email address.

    Use this to identify a person in Rosalind. Returns people whose display
    name or primary email contains the query. This is a person lookup, not a
    general personal-data search.
    """
    with SessionLocal() as session:
        results = composition.build_person_service(session).search_people(query)
    return [_to_result(profile) for profile in results]


@mcp.tool()
def get_person(person_id: uuid.UUID) -> PersonProfileResult | None:
    """Retrieve the canonical profile of a specific person.

    Use this after identifying a person with search_people. Returns None if no
    such person exists.
    """
    with SessionLocal() as session:
        profile = composition.build_person_service(session).get_person(person_id)
    return _to_result(profile) if profile is not None else None


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
