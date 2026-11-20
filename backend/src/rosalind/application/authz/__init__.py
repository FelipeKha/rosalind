"""Access-policy enforcement domain (Phase 2).

Pure, framework-free representations of an effective access scope. The SQL
adapter compiles this scope into predicates; the reference evaluator in
``models`` is the independent oracle used by L2 verification and property tests.
"""

from rosalind.application.authz.evaluator import build_effective_scope
from rosalind.application.authz.models import (
    AccessAttributes,
    AccessClause,
    AccessEnforcementLevels,
    EffectiveScope,
    LoadedAccessPolicies,
    LoadedPolicy,
    ParticipantTerm,
    PolicyDecision,
    deny_all_scope,
    empty_scope,
    scope_from_clauses,
)

__all__ = [
    "AccessAttributes",
    "AccessClause",
    "AccessEnforcementLevels",
    "EffectiveScope",
    "LoadedAccessPolicies",
    "LoadedPolicy",
    "ParticipantTerm",
    "PolicyDecision",
    "build_effective_scope",
    "deny_all_scope",
    "empty_scope",
    "scope_from_clauses",
]
