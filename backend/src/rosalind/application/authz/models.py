"""Pure access-scope value objects and the reference evaluator.

An ``EffectiveScope`` is the compiled form of one account's active access
policies. It is intentionally independent of SQLAlchemy, FastAPI and the policy
interpreter: only the canonical ``PolicySpec`` models feed it.

Semantics (deliberately different from the design document's default-deny):

* no permit policies -> implicit permit-all; deny rules still apply;
* a deny clause that matches the item always hides it;
* an empty deny clause hides everything;
* policy or validation errors are handled by the loader as ``DENY_ALL``, never
  as implicit permit-all.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum

from rosalind.policy.domain.spec import AccessPolicySpec

_ALL_ROLES = frozenset({"from", "to", "cc", "bcc"})


@dataclass(frozen=True, slots=True)
class AccessEnforcementLevels:
    """Per-stage enforcement switches carried on the search plan.

    Configuration is mapped into this plain type at the composition boundary so
    the application layer never imports settings. A disabled level omits the
    access predicate at that stage; it does not skip the operation.
    """

    lexical: bool = True
    semantic: bool = True
    listing: bool = True
    metadata: bool = True
    thread: bool = True
    assembly: bool = True
    verification: bool = True

    @property
    def output_safe(self) -> bool:
        """Whether at least one output safety net is enabled."""
        return self.assembly or self.verification

    def enabled_names(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                "lexical",
                "semantic",
                "listing",
                "metadata",
                "thread",
                "assembly",
                "verification",
            )
            if getattr(self, name)
        )

    def disabled_names(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                "lexical",
                "semantic",
                "listing",
                "metadata",
                "thread",
                "assembly",
                "verification",
            )
            if not getattr(self, name)
        )


class PolicyDecision(StrEnum):
    PERMIT_ALL = "permit_all"
    SCOPED = "scoped"
    DENY_ALL = "deny_all"


@dataclass(frozen=True, slots=True)
class AccessAttributes:
    """The authorization-relevant attributes of one candidate item."""

    source_account_id: uuid.UUID
    sent_at: datetime
    from_handles: frozenset[str] = frozenset()
    to_handles: frozenset[str] = frozenset()
    cc_handles: frozenset[str] = frozenset()
    bcc_handles: frozenset[str] = frozenset()
    participant_handles: frozenset[str] = frozenset()
    direction: str = "unknown"


@dataclass(frozen=True, slots=True)
class ParticipantTerm:
    """A participant condition: any of ``addresses`` in any of ``roles``."""

    addresses: frozenset[str]
    roles: frozenset[str] = _ALL_ROLES

    def matches(self, attrs: AccessAttributes) -> bool:
        if not self.addresses:
            return False
        roles = self.roles or _ALL_ROLES
        if roles == _ALL_ROLES:
            return bool(self.addresses & attrs.participant_handles)
        handles: set[str] = set()
        for role in roles:
            handles.update(_role_handles(attrs, role))
        return bool(self.addresses & handles)


@dataclass(frozen=True, slots=True)
class AccessClause:
    """A conjunction of account/date/direction and participant terms."""

    participants: tuple[ParticipantTerm, ...] = ()
    source_account_id: uuid.UUID | None = None
    sent_from: datetime | None = None
    sent_before: datetime | None = None
    direction: str | None = None

    def matches(self, attrs: AccessAttributes) -> bool:
        if (
            self.source_account_id is not None
            and attrs.source_account_id != self.source_account_id
        ):
            return False
        if self.sent_from is not None and attrs.sent_at < self.sent_from:
            return False
        if self.sent_before is not None and attrs.sent_at >= self.sent_before:
            return False
        if self.direction is not None and attrs.direction != self.direction:
            return False
        return all(term.matches(attrs) for term in self.participants)

    def is_unconstrained(self) -> bool:
        return not (
            self.participants
            or self.source_account_id is not None
            or self.sent_from is not None
            or self.sent_before is not None
            or self.direction is not None
        )


@dataclass(frozen=True, slots=True)
class LoadedPolicy:
    """One active access policy revision as loaded from storage."""

    policy_id: uuid.UUID
    revision: int
    spec: AccessPolicySpec


@dataclass(frozen=True, slots=True)
class LoadedAccessPolicies:
    """The raw loader output, before clauses are compiled."""

    policy_version: int
    policies: tuple[LoadedPolicy, ...]
    address_lookup: Mapping[uuid.UUID, frozenset[str]]


@dataclass(frozen=True, slots=True)
class EffectiveScope:
    """The compiled access scope for one account at one policy version."""

    account_id: uuid.UUID
    policy_version: int
    permits: tuple[AccessClause, ...]
    denies: tuple[AccessClause, ...]
    implicit_permit_all: bool
    decision: PolicyDecision
    scope_fingerprint: str
    policy_ids: tuple[str, ...] = ()

    def is_visible(self, attrs: AccessAttributes) -> bool:
        if self.decision is PolicyDecision.DENY_ALL:
            return False
        if not self.implicit_permit_all and not any(
            clause.matches(attrs) for clause in self.permits
        ):
            return False
        return not any(clause.matches(attrs) for clause in self.denies)


def scope_from_clauses(
    account_id: uuid.UUID,
    *,
    policy_version: int,
    permits: tuple[AccessClause, ...],
    denies: tuple[AccessClause, ...],
    policy_ids: tuple[str, ...] = (),
) -> EffectiveScope:
    """Compile clauses with the implicit-permit-all rule applied."""
    return _finalize(
        account_id=account_id,
        policy_version=policy_version,
        permits=permits,
        denies=denies,
        implicit_permit_all=not permits,
        policy_ids=policy_ids,
    )


def empty_scope(account_id: uuid.UUID, *, policy_version: int = 0) -> EffectiveScope:
    """An implicit permit-all scope with no denies (used when no policy applies)."""
    return _finalize(
        account_id=account_id,
        policy_version=policy_version,
        permits=(),
        denies=(),
        implicit_permit_all=True,
        policy_ids=(),
    )


def deny_all_scope(
    account_id: uuid.UUID,
    *,
    policy_version: int = 0,
    policy_ids: tuple[str, ...] = (),
) -> EffectiveScope:
    """A fail-closed scope used when policies exist but cannot be evaluated."""
    return _finalize(
        account_id=account_id,
        policy_version=policy_version,
        permits=(),
        denies=(),
        implicit_permit_all=False,
        policy_ids=policy_ids,
        decision=PolicyDecision.DENY_ALL,
    )


def _finalize(
    *,
    account_id: uuid.UUID,
    policy_version: int,
    permits: tuple[AccessClause, ...],
    denies: tuple[AccessClause, ...],
    implicit_permit_all: bool,
    policy_ids: tuple[str, ...],
    decision: PolicyDecision | None = None,
) -> EffectiveScope:
    if decision is None:
        if any(clause.is_unconstrained() for clause in denies):
            decision = PolicyDecision.DENY_ALL
        elif implicit_permit_all:
            decision = PolicyDecision.PERMIT_ALL
        else:
            decision = PolicyDecision.SCOPED
    fingerprint = _fingerprint(
        account_id=account_id,
        policy_version=policy_version,
        permits=permits,
        denies=denies,
        implicit_permit_all=implicit_permit_all,
        decision=decision,
    )
    return EffectiveScope(
        account_id=account_id,
        policy_version=policy_version,
        permits=permits,
        denies=denies,
        implicit_permit_all=implicit_permit_all,
        decision=decision,
        scope_fingerprint=fingerprint,
        policy_ids=policy_ids,
    )


def _role_handles(attrs: AccessAttributes, role: str) -> frozenset[str]:
    if role == "from":
        return attrs.from_handles
    if role == "to":
        return attrs.to_handles
    if role == "cc":
        return attrs.cc_handles
    if role == "bcc":
        return attrs.bcc_handles
    return attrs.participant_handles


def date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def date_end_exclusive(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _canonical_clause(clause: AccessClause) -> dict[str, object]:
    terms = [
        {
            "addresses": sorted(term.addresses),
            "roles": sorted(term.roles or _ALL_ROLES),
        }
        for term in clause.participants
    ]
    terms.sort(key=_canonical_json)
    return {
        "participants": terms,
        "source_account": (
            str(clause.source_account_id)
            if clause.source_account_id is not None
            else None
        ),
        "sent_from": clause.sent_from.isoformat() if clause.sent_from else None,
        "sent_before": clause.sent_before.isoformat() if clause.sent_before else None,
        "direction": clause.direction,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _fingerprint(
    *,
    account_id: uuid.UUID,
    policy_version: int,
    permits: tuple[AccessClause, ...],
    denies: tuple[AccessClause, ...],
    implicit_permit_all: bool,
    decision: PolicyDecision,
) -> str:
    payload = {
        "account": str(account_id),
        "policy_version": policy_version,
        "implicit_permit_all": implicit_permit_all,
        "decision": decision.value,
        "permits": sorted(
            (_canonical_clause(clause) for clause in permits), key=_canonical_json
        ),
        "denies": sorted(
            (_canonical_clause(clause) for clause in denies), key=_canonical_json
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
