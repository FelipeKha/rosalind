"""Unit tests for the access-policy domain and reference evaluator."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from rosalind.application.authz import (
    AccessAttributes,
    LoadedAccessPolicies,
    LoadedPolicy,
    PolicyDecision,
    build_effective_scope,
    scope_from_clauses,
)
from rosalind.application.authz.models import (
    AccessClause,
    ParticipantTerm,
    date_end_exclusive,
    date_start,
)
from rosalind.policy.domain.spec import AccessPolicySpec, validate_spec

ACCOUNT = uuid.uuid4()
PERSON = uuid.uuid4()
JOHN = "john.smith@acme.com"
MARY = "mary@example.com"


def _attrs(
    *,
    sender=JOHN,
    to=(MARY,),
    cc=(),
    bcc=(),
    participants=None,
    sent_at=datetime(2026, 1, 15, 12, tzinfo=UTC),
    direction="received",
    account=ACCOUNT,
) -> AccessAttributes:
    if participants is None:
        participants = {sender, *to, *cc, *bcc}
    return AccessAttributes(
        source_account_id=account,
        sent_at=sent_at,
        from_handles=frozenset({sender}),
        to_handles=frozenset(to),
        cc_handles=frozenset(cc),
        bcc_handles=frozenset(bcc),
        participant_handles=frozenset(participants),
        direction=direction,
    )


def _spec(effect: str, predicates: list[dict]) -> AccessPolicySpec:
    payload = {
        "schema_version": "rosalind.policy.v2",
        "type": "access",
        "effect": effect,
        "principal": {"type": "all_agents"},
        "resource": {
            "type": "email",
            "selector": {"operator": "all_of", "predicates": predicates},
        },
        "status": "active",
    }
    spec = validate_spec(payload)
    assert isinstance(spec, AccessPolicySpec)
    return spec


def _participant(
    *,
    roles: list[str] | None = None,
    addresses: list[str] | None = None,
    person_id: uuid.UUID | None = None,
) -> dict:
    predicate: dict[str, object] = {
        "operator": "has_participant",
        "roles": roles or ["from", "to", "cc", "bcc"],
    }
    if addresses is not None:
        predicate["addresses"] = addresses
    if person_id is not None:
        predicate["person_id"] = str(person_id)
    return predicate


def _scope(*specs: AccessPolicySpec, lookup: dict | None = None):
    return build_effective_scope(
        ACCOUNT,
        LoadedAccessPolicies(
            policy_version=3,
            policies=tuple(
                LoadedPolicy(policy_id=uuid.uuid4(), revision=1, spec=spec)
                for spec in specs
            ),
            address_lookup=lookup or {},
        ),
    )


def test_no_policies_is_implicit_permit_all() -> None:
    scope = _scope()
    assert scope.decision is PolicyDecision.PERMIT_ALL
    assert scope.is_visible(_attrs())


def test_deny_only_hides_matching_items() -> None:
    scope = _scope(_spec("deny", [_participant(addresses=[JOHN], roles=["from"])]))
    assert not scope.is_visible(_attrs(sender=JOHN))
    assert scope.is_visible(_attrs(sender="other@example.com"))


def test_permit_list_narrows_the_visible_set() -> None:
    scope = _scope(_spec("permit", [_participant(addresses=[JOHN], roles=["from"])]))
    assert scope.decision is PolicyDecision.SCOPED
    assert scope.is_visible(_attrs(sender=JOHN))
    assert not scope.is_visible(_attrs(sender="other@example.com"))


def test_deny_overrides_permit() -> None:
    scope = _scope(
        _spec("permit", [_participant(addresses=[JOHN], roles=["from"])]),
        _spec("deny", [_participant(addresses=[JOHN], roles=["from"])]),
    )
    assert not scope.is_visible(_attrs(sender=JOHN))


def test_roles_are_respected() -> None:
    scope = _scope(_spec("deny", [_participant(addresses=[MARY], roles=["cc"])]))
    assert not scope.is_visible(_attrs(cc=[MARY]))
    assert scope.is_visible(_attrs(to=[MARY]))


def test_person_addresses_are_expanded() -> None:
    scope = _scope(
        _spec("deny", [_participant(addresses=[JOHN], person_id=PERSON)]),
        lookup={PERSON: frozenset({"new-john@acme.com"})},
    )
    assert not scope.is_visible(_attrs(sender=JOHN))
    assert not scope.is_visible(_attrs(sender="new-john@acme.com"))


def test_date_range_is_half_open_utc() -> None:
    scope = _scope(
        _spec(
            "deny",
            [
                {
                    "operator": "date_range",
                    "from": "2026-01-01",
                    "to": "2026-02-01",
                }
            ],
        )
    )
    assert not scope.is_visible(_attrs(sent_at=date_start(date(2026, 1, 1))))
    assert scope.is_visible(_attrs(sent_at=date_end_exclusive(date(2026, 2, 1))))
    assert scope.is_visible(_attrs(sent_at=date_start(date(2026, 2, 1))))


def test_account_and_direction_predicates() -> None:
    scope = _scope(
        _spec(
            "deny",
            [
                {
                    "operator": "in_account",
                    "source_account_id": str(ACCOUNT),
                },
                {"operator": "direction", "direction": "received"},
            ],
        )
    )
    assert not scope.is_visible(_attrs(account=ACCOUNT, direction="received"))
    assert scope.is_visible(_attrs(account=uuid.uuid4(), direction="received"))
    assert scope.is_visible(_attrs(account=ACCOUNT, direction="sent"))


def test_unconstrained_deny_is_deny_all() -> None:
    scope = scope_from_clauses(
        ACCOUNT,
        policy_version=1,
        permits=(),
        denies=(AccessClause(),),
    )
    assert scope.decision is PolicyDecision.DENY_ALL
    assert not scope.is_visible(_attrs())


def test_fingerprint_is_stable_and_order_independent() -> None:
    first = _scope(
        _spec("deny", [_participant(addresses=[JOHN], roles=["from"])]),
        _spec("deny", [_participant(addresses=[MARY], roles=["to"])]),
    )
    second = _scope(
        _spec("deny", [_participant(addresses=[MARY], roles=["to"])]),
        _spec("deny", [_participant(addresses=[JOHN], roles=["from"])]),
    )
    assert first.scope_fingerprint == second.scope_fingerprint

    changed = _scope(_spec("deny", [_participant(addresses=[JOHN], roles=["from"])]))
    assert changed.scope_fingerprint != first.scope_fingerprint


def test_empty_participant_term_never_matches() -> None:
    clause = AccessClause(participants=(ParticipantTerm(addresses=frozenset()),))
    assert not clause.matches(_attrs())
