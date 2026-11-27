"""Pure confidentiality-scope value objects.

A ``SemanticScope`` is the compiled form of one account's confidentiality
policies for a request. It names the protected statements, their match levels,
the treatment, and whether the rule is still building. It never contains
statement text: statements are encrypted and live only in the policy service's
storage.

``set_id`` identifies the exact combination of statements + treatments. Overlay
rows are keyed by it so agents with identical statements share sanitized text,
independent of their access scopes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

__all__ = ["SemanticScope", "SemanticStatement", "Treatment"]


@dataclass(frozen=True, slots=True)
class Treatment:
    """How a protected span is rendered when a statement matches."""

    mode: str = "redact_span"
    fallback: str = "drop_segment"

    def __post_init__(self) -> None:
        if self.mode != "redact_span":
            raise ValueError(f"unsupported treatment mode: {self.mode}")
        if self.fallback != "drop_segment":
            raise ValueError(f"unsupported treatment fallback: {self.fallback}")


@dataclass(frozen=True, slots=True)
class SemanticStatement:
    """One protected statement as it applies to a request."""

    policy_id: str
    statement_id: str
    match_levels: tuple[str, ...] = ("asserts", "implies", "evidence")
    treatment: Treatment = Treatment()
    status: str = "building"
    hold_until_ready: bool = False

    def __post_init__(self) -> None:
        if self.status not in ("building", "active"):
            raise ValueError(f"unsupported statement status: {self.status}")


@dataclass(frozen=True, slots=True)
class SemanticScope:
    """The semantic set for one account at one policy version."""

    account_id: uuid.UUID
    policy_version: int
    statements: tuple[SemanticStatement, ...]
    set_id: str

    @property
    def is_empty(self) -> bool:
        return not self.statements

    @property
    def holds_until_ready(self) -> bool:
        return any(
            statement.hold_until_ready and statement.status != "active"
            for statement in self.statements
        )

    @classmethod
    def build(
        cls,
        *,
        account_id: uuid.UUID,
        policy_version: int,
        statements: tuple[SemanticStatement, ...],
    ) -> SemanticScope:
        return cls(
            account_id=account_id,
            policy_version=policy_version,
            statements=statements,
            set_id=_set_id(statements),
        )


def _set_id(statements: tuple[SemanticStatement, ...]) -> str:
    payload = sorted(
        (
            {
                "policy_id": statement.policy_id,
                "statement_id": statement.statement_id,
                "match_levels": sorted(statement.match_levels),
                "mode": statement.treatment.mode,
                "fallback": statement.treatment.fallback,
            }
            for statement in statements
        ),
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
