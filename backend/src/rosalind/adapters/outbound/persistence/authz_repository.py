"""Read-only loader for active access policies.

The data backend shares PostgreSQL with the policy service but keeps a narrow
read boundary: this adapter reads only the policy identity/revision tables and
the person/email directory needed to expand selectors. It never reads email
bodies or writes policy rows.

Policy JSONB is validated through the canonical ``PolicySpec`` models. A
validation failure raises ``AccessPolicyError`` so the caller can fail closed.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.models.base import utcnow
from rosalind.application.authz.errors import AccessPolicyError
from rosalind.application.authz.models import (
    AccessAttributes,
    LoadedAccessPolicies,
    LoadedPolicy,
)
from rosalind.application.search import SearchPlan
from rosalind.policy.domain.spec import (
    AccessPolicySpec,
    HasParticipantPredicate,
    PrincipalType,
    validate_spec,
)

__all__ = [
    "PostgresAccessPolicyRepository",
    "PostgresAccessVerifier",
    "PostgresSecurityEventRepository",
]

_METADATA = sa.MetaData()

_POLICY = sa.Table(
    "policy",
    _METADATA,
    sa.Column("id", sa.Uuid()),
    sa.Column("account_id", sa.Uuid()),
    sa.Column("policy_type", sa.Text()),
    sa.Column("status", sa.Text()),
    sa.Column("principal_kind", sa.Text()),
    sa.Column("current_revision", sa.Integer()),
    schema="authz",
)

_POLICY_REVISION = sa.Table(
    "policy_revision",
    _METADATA,
    sa.Column("policy_id", sa.Uuid()),
    sa.Column("revision", sa.Integer()),
    sa.Column("spec", JSONB()),
    schema="authz",
)

_POLICY_VERSION = sa.Table(
    "policy_version",
    _METADATA,
    sa.Column("account_id", sa.Uuid()),
    sa.Column("version", sa.BigInteger()),
    schema="authz",
)

_SECURITY_EVENT = sa.Table(
    "security_event",
    _METADATA,
    sa.Column("id", sa.Uuid()),
    sa.Column("account_id", sa.Uuid()),
    sa.Column("request_id", sa.Uuid()),
    sa.Column("event", sa.Text()),
    sa.Column("detail", JSONB()),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    schema="audit",
)


class PostgresAccessPolicyRepository:
    """Implements ``AccessPolicyRepository`` on short-lived sessions."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._factory = session_factory

    async def load_access_policies(self, account_id: uuid.UUID) -> LoadedAccessPolicies:
        return await asyncio.to_thread(self._load, account_id)

    def _load(self, account_id: uuid.UUID) -> LoadedAccessPolicies:
        with self._factory() as session:
            rows = session.execute(
                sa.select(
                    _POLICY.c.id,
                    _POLICY_REVISION.c.revision,
                    _POLICY_REVISION.c.spec,
                )
                .select_from(_POLICY)
                .join(
                    _POLICY_REVISION,
                    sa.and_(
                        _POLICY_REVISION.c.policy_id == _POLICY.c.id,
                        _POLICY_REVISION.c.revision == _POLICY.c.current_revision,
                    ),
                )
                .where(
                    _POLICY.c.account_id == account_id,
                    _POLICY.c.policy_type == "access",
                    _POLICY.c.status == "active",
                    _POLICY.c.principal_kind == "all_agents",
                )
                .order_by(_POLICY.c.id)
            ).all()

            policies: list[LoadedPolicy] = []
            person_ids: set[uuid.UUID] = set()
            for policy_id, revision, payload in rows:
                try:
                    spec = validate_spec(payload)
                except Exception as exc:
                    raise AccessPolicyError(
                        f"active policy {policy_id} revision {revision} is invalid"
                    ) from exc
                if not isinstance(spec, AccessPolicySpec):
                    continue
                if spec.principal.type is not PrincipalType.ALL_AGENTS:
                    continue
                policies.append(
                    LoadedPolicy(policy_id=policy_id, revision=revision, spec=spec)
                )
                person_ids.update(_person_ids(spec))

            address_lookup = _address_lookup(session, person_ids)
            version = session.scalar(
                sa.select(_POLICY_VERSION.c.version).where(
                    _POLICY_VERSION.c.account_id == account_id
                )
            )
            return LoadedAccessPolicies(
                policy_version=int(version or 0),
                policies=tuple(policies),
                address_lookup=address_lookup,
            )


class PostgresAccessVerifier:
    """L2 verifier: fetch raw attributes and re-evaluate in Python.

    Deliberately does not call the SQL compiler. The only shared piece is the
    pure reference evaluator on ``EffectiveScope``.
    """

    def __init__(self, session_factory: Callable[[], Session]):
        self._factory = session_factory

    async def visible_item_ids(
        self, plan: SearchPlan, item_ids: tuple[uuid.UUID, ...]
    ) -> frozenset[uuid.UUID]:
        return await asyncio.to_thread(self._visible, plan, item_ids)

    def _visible(
        self, plan: SearchPlan, item_ids: tuple[uuid.UUID, ...]
    ) -> frozenset[uuid.UUID]:
        if plan.access_scope is None:
            return frozenset(item_ids)
        if not item_ids:
            return frozenset()

        chunk = models.Chunk
        with self._factory() as session:
            rows = session.execute(
                sa.select(
                    chunk.email_id,
                    chunk.sent_at,
                    chunk.source_account_id,
                    chunk.direction,
                    chunk.from_handles,
                    chunk.to_handles,
                    chunk.cc_handles,
                    chunk.bcc_handles,
                    chunk.participant_handles,
                ).where(
                    chunk.email_id.in_(item_ids),
                    chunk.source_account_id.in_(plan.scope.source_account_ids),
                )
            ).all()

        attributes: dict[uuid.UUID, AccessAttributes] = {}
        for (
            email_id,
            sent_at,
            source_account_id,
            direction,
            from_handles,
            to_handles,
            cc_handles,
            bcc_handles,
            participant_handles,
        ) in rows:
            attributes.setdefault(
                email_id,
                AccessAttributes(
                    source_account_id=source_account_id,
                    sent_at=sent_at,
                    from_handles=frozenset(from_handles or ()),
                    to_handles=frozenset(to_handles or ()),
                    cc_handles=frozenset(cc_handles or ()),
                    bcc_handles=frozenset(bcc_handles or ()),
                    participant_handles=frozenset(participant_handles or ()),
                    direction=direction,
                ),
            )

        return frozenset(
            item_id
            for item_id in item_ids
            if (attrs := attributes.get(item_id)) is not None
            and plan.access_scope.is_visible(attrs)
        )


class PostgresSecurityEventRepository:
    """Implements ``SecurityEventPort`` with content-free audit rows."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._factory = session_factory

    async def record(
        self,
        *,
        account_id: uuid.UUID | None,
        request_id: uuid.UUID | None,
        event: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._record, account_id, request_id, event, detail or {}
        )

    def _record(
        self,
        account_id: uuid.UUID | None,
        request_id: uuid.UUID | None,
        event: str,
        detail: dict[str, object],
    ) -> None:
        with self._factory() as session:
            session.execute(
                sa.insert(_SECURITY_EVENT).values(
                    id=uuid.uuid4(),
                    account_id=account_id,
                    request_id=request_id,
                    event=event,
                    detail=detail,
                    created_at=utcnow(),
                )
            )
            session.commit()


def _person_ids(spec: AccessPolicySpec) -> set[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    for predicate in spec.resource.selector.predicates:
        if isinstance(predicate, HasParticipantPredicate) and predicate.person_id:
            try:
                ids.add(uuid.UUID(predicate.person_id))
            except ValueError, AttributeError:
                continue
    return ids


def _address_lookup(
    session: Session, person_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, frozenset[str]]:
    ids = list(person_ids)
    if not ids:
        return {}
    grouped: dict[uuid.UUID, set[str]] = defaultdict(set)
    rows = session.execute(
        sa.select(
            models.PersonEmail.person_id,
            models.PersonEmail.email_normalized,
        ).where(models.PersonEmail.person_id.in_(ids))
    ).all()
    for person_id, address in rows:
        if address:
            grouped[person_id].add(address.strip().lower())
    return {person_id: frozenset(addresses) for person_id, addresses in grouped.items()}
