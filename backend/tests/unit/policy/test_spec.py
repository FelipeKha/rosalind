from __future__ import annotations

import pytest
from pydantic import ValidationError

from rosalind.policy.domain.spec import (
    AccessPolicySpec,
    DateRangePredicate,
    EmailResource,
    HasParticipantPredicate,
    PolicyStatus,
    Principal,
    PrincipalType,
    Selector,
    validate_spec,
)


def test_all_agents_principal_rejects_id() -> None:
    with pytest.raises(ValidationError):
        Principal(type=PrincipalType.ALL_AGENTS, id="agent_a")


def test_agent_principal_requires_id() -> None:
    with pytest.raises(ValidationError):
        Principal(type=PrincipalType.AGENT)


def test_access_spec_requires_non_empty_selector() -> None:
    with pytest.raises(ValidationError):
        Selector(predicates=[])


def test_has_participant_requires_address_or_person() -> None:
    with pytest.raises(ValidationError):
        HasParticipantPredicate(roles=["from"])


def test_date_range_validates_order() -> None:
    with pytest.raises(ValidationError):
        DateRangePredicate.model_validate({"from": "2025-02-01", "to": "2025-01-01"})


def test_validate_spec_round_trips_access() -> None:
    spec = AccessPolicySpec(
        effect="deny",
        principal=Principal(type=PrincipalType.ALL_AGENTS),
        resource=EmailResource(
            selector=Selector(
                predicates=[
                    HasParticipantPredicate(
                        roles=["from"],
                        addresses=["john@example.com"],
                        person_id="person_123",
                    )
                ]
            )
        ),
        status=PolicyStatus.ACTIVE,
    )
    dumped = spec.model_dump(mode="json", by_alias=True, exclude_none=True)

    parsed = validate_spec(dumped)

    assert parsed.type == "access"
    assert parsed.principal.type is PrincipalType.ALL_AGENTS
    assert dumped["resource"]["selector"]["predicates"][0]["operator"] == (
        "has_participant"
    )
