"""Compile active ``AccessPolicySpec`` revisions into an ``EffectiveScope``.

The local policy interpreter only produces ``all_agents`` access policies today,
so the loader passes those through. Evaluation is deterministic and pure; the
same functions back L2 verification.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from rosalind.application.authz.models import (
    AccessClause,
    EffectiveScope,
    LoadedAccessPolicies,
    ParticipantTerm,
    date_end_exclusive,
    date_start,
    scope_from_clauses,
)
from rosalind.policy.domain.spec import (
    AccessPolicySpec,
    DateRangePredicate,
    DirectionPredicate,
    Effect,
    HasParticipantPredicate,
    InAccountPredicate,
    PrincipalType,
    Role,
)

_ALL_ROLES = frozenset(role.value for role in Role)


def build_effective_scope(
    account_id: uuid.UUID, loaded: LoadedAccessPolicies
) -> EffectiveScope:
    """Build the account's scope. Callers fail closed on loader errors."""
    permits: list[AccessClause] = []
    denies: list[AccessClause] = []
    policy_ids: list[str] = []

    for loaded_policy in loaded.policies:
        spec = loaded_policy.spec
        if spec.principal.type is not PrincipalType.ALL_AGENTS:
            # Agent-specific policies are not enforceable until the agent
            # registry exists. Ignoring them is safe for permits and denies:
            # they simply do not apply yet.
            continue
        clause = _clause_from_spec(spec, loaded.address_lookup)
        if spec.effect is Effect.PERMIT:
            permits.append(clause)
        else:
            denies.append(clause)
        policy_ids.append(f"{loaded_policy.policy_id}:{loaded_policy.revision}")

    return scope_from_clauses(
        account_id,
        policy_version=loaded.policy_version,
        permits=tuple(permits),
        denies=tuple(denies),
        policy_ids=tuple(sorted(policy_ids)),
    )


def _clause_from_spec(
    spec: AccessPolicySpec,
    address_lookup: Mapping[uuid.UUID, frozenset[str]],
) -> AccessClause:
    participants: list[ParticipantTerm] = []
    source_account_id: uuid.UUID | None = None
    sent_from = None
    sent_before = None
    direction: str | None = None

    for predicate in spec.resource.selector.predicates:
        if isinstance(predicate, HasParticipantPredicate):
            participants.append(_participant_term(predicate, address_lookup))
        elif isinstance(predicate, InAccountPredicate):
            source_account_id = _uuid(predicate.source_account_id)
        elif isinstance(predicate, DateRangePredicate):
            sent_from, sent_before = _date_bounds(predicate)
        elif isinstance(predicate, DirectionPredicate):
            direction = predicate.direction

    return AccessClause(
        participants=tuple(participants),
        source_account_id=source_account_id,
        sent_from=sent_from,
        sent_before=sent_before,
        direction=direction,
    )


def _participant_term(
    predicate: HasParticipantPredicate,
    address_lookup: Mapping[uuid.UUID, frozenset[str]],
) -> ParticipantTerm:
    addresses = {
        address.strip().lower() for address in predicate.addresses if address.strip()
    }
    if predicate.person_id:
        person_id = _uuid(predicate.person_id)
        if person_id is not None:
            addresses.update(address_lookup.get(person_id, frozenset()))

    roles = frozenset(role.value for role in predicate.roles) or _ALL_ROLES
    return ParticipantTerm(addresses=frozenset(addresses), roles=roles)


def _date_bounds(predicate: DateRangePredicate):
    sent_from = date_start(predicate.from_date) if predicate.from_date else None
    sent_before = date_end_exclusive(predicate.to) if predicate.to else None
    return sent_from, sent_before


def _uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError, AttributeError:
        return None


__all__ = ["build_effective_scope"]
