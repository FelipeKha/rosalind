"""Integration tests for access-policy loading, SQL compilation and L2.

These exercise the real policy tables and ``search.chunk`` role arrays against
PostgreSQL. The policy service and data backend share the database, so the test
inserts confirmed policy revisions through the policy ORM models.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.authz_repository import (
    PostgresAccessPolicyRepository,
    PostgresAccessVerifier,
)
from rosalind.adapters.outbound.search.filters import (
    filter_conditions,
    scope_conditions,
)
from rosalind.adapters.outbound.search.search_repository import PostgresSearchRepository
from rosalind.application.authz import (
    AccessEnforcementLevels,
    build_effective_scope,
)
from rosalind.application.authz.errors import AccessPolicyError
from rosalind.application.search import (
    Budgets,
    FusionConfig,
    GroupBy,
    PreparedQuery,
    Presentation,
    RequestContext,
    ResolvedFilters,
    ResultView,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SortOrder,
)
from rosalind.application.search.plan import IndexVersions
from rosalind.policy.adapters.persistence import (
    PolicyModel,
    PolicyRevisionModel,
    PolicyVersionModel,
)

JOHN = "john.smith@acme.com"
NEW_JOHN = "new-john@acme.com"
MARY = "mary@example.com"
SENT_AT = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


def _source(session: Session, account_id: uuid.UUID, name: str):
    source = models.SourceAccount(account_id=account_id, provider="google", name=name)
    session.add(source)
    session.flush()
    return source


def _person_with_addresses(session: Session, *addresses: str):
    person = models.Person(id=uuid.uuid4())
    session.add(person)
    session.flush()
    for index, address in enumerate(addresses):
        session.add(
            models.PersonEmail(
                id=uuid.uuid4(),
                person_id=person.id,
                email=address,
                email_normalized=address.lower(),
                is_primary=index == 0,
                is_verified=False,
            )
        )
    session.flush()
    return person


def _email_and_chunk(
    session: Session,
    source,
    *,
    from_handles: tuple[str, ...],
    to_handles: tuple[str, ...] = (),
    cc_handles: tuple[str, ...] = (),
    bcc_handles: tuple[str, ...] = (),
    direction: str = "received",
    sent_at: datetime = SENT_AT,
    thread_id: uuid.UUID | None = None,
):
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source.id,
        message_id=f"message-{uuid.uuid4()}",
        message_id_synthetic=False,
        occurred_at=sent_at,
        direction=direction,
        subject="subject",
        has_attachments=False,
        is_trash_or_spam=False,
        thread_id=thread_id,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    session.add(message)
    session.flush()

    participants = sorted({*from_handles, *to_handles, *cc_handles, *bcc_handles})
    session.add(
        models.Chunk(
            id=uuid.uuid4(),
            email_id=message.id,
            chunk_kind="email_body",
            seq=0,
            text_for_display="hello",
            text_for_index="hello",
            text_sha256=f"sha-{uuid.uuid4()}",
            language="en",
            index_version="v1",
            source_account_id=source.id,
            source_account_num=source.num,
            sent_at=sent_at,
            sender_handle=from_handles[0] if from_handles else "",
            recipient_handles=sorted({*to_handles, *cc_handles, *bcc_handles}),
            participant_handles=participants,
            from_handles=list(from_handles),
            to_handles=list(to_handles),
            cc_handles=list(cc_handles),
            bcc_handles=list(bcc_handles),
            direction=direction,
            has_attachment=False,
            is_trash_or_spam=False,
            tags=[],
            meta={},
        )
    )
    session.flush()
    return message


def _add_policy(
    session: Session,
    account_id: uuid.UUID,
    *,
    effect: str,
    roles: list[str],
    addresses: list[str] | None = None,
    person_id: uuid.UUID | None = None,
    extra_predicates: list[dict] | None = None,
    version: int = 1,
):
    predicate: dict[str, object] = {
        "operator": "has_participant",
        "roles": roles,
    }
    if addresses is not None:
        predicate["addresses"] = addresses
    if person_id is not None:
        predicate["person_id"] = str(person_id)
    predicates = [predicate, *(extra_predicates or [])]

    policy = PolicyModel(
        account_id=account_id,
        title="test",
        principal_kind="all_agents",
        policy_type="access",
        status="active",
        current_revision=1,
    )
    session.add(policy)
    session.flush()
    session.add(
        PolicyRevisionModel(
            policy_id=policy.id,
            revision=1,
            spec={
                "schema_version": "rosalind.policy.v2",
                "type": "access",
                "effect": effect,
                "principal": {"type": "all_agents"},
                "resource": {
                    "type": "email",
                    "selector": {
                        "operator": "all_of",
                        "predicates": predicates,
                    },
                },
                "status": "active",
            },
            source_encrypted="test",
            interpreter_version="test",
            model_id="test",
        )
    )
    existing_version = session.get(PolicyVersionModel, account_id)
    if existing_version is None:
        session.add(PolicyVersionModel(account_id=account_id, version=version))
    session.commit()
    return policy


def _repo(engine: Engine) -> PostgresAccessPolicyRepository:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return PostgresAccessPolicyRepository(factory)


def _scope(engine: Engine, account_id: uuid.UUID):
    loaded = asyncio.run(_repo(engine).load_access_policies(account_id))
    return build_effective_scope(account_id, loaded)


def _visible(engine: Engine, source, scope) -> set[uuid.UUID]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        return set(
            session.scalars(
                select(models.Chunk.email_id).where(
                    models.Chunk.source_account_id == source.id,
                    *scope_conditions(scope),
                )
            )
        )


def _plan(account_id: uuid.UUID, source, scope) -> SearchPlan:
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(account_id=account_id, source_account_ids=frozenset({source.id})),
        filters=ResolvedFilters(),
        resolved_entities=(),
        query=PreparedQuery(),
        strategy=SearchStrategy.LIST,
        mode_requested=SearchMode.LEXICAL,
        mode_effective=SearchMode.LEXICAL,
        presentation=Presentation(
            sort=SortOrder.DATE_DESC,
            group_by=GroupBy.MESSAGE,
            view=ResultView.METADATA,
            limit=10,
        ),
        budgets=Budgets(
            lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=25
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=None,
        ),
        fusion=FusionConfig(),
        access_scope=scope,
    )


def test_deny_from_hides_only_sender(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    john = _person_with_addresses(migrated_db_session, JOHN)
    e6 = _email_and_chunk(
        migrated_db_session, source, from_handles=(JOHN,), to_handles=(MARY,)
    )
    e7 = _email_and_chunk(
        migrated_db_session,
        source,
        from_handles=(MARY,),
        to_handles=(MARY,),
        cc_handles=(JOHN,),
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="deny",
        roles=["from"],
        person_id=john.id,
    )

    scope = _scope(migrated_engine, account.id)
    visible = _visible(migrated_engine, source, scope)
    assert e6.id not in visible
    assert e7.id in visible


def test_deny_cc_is_role_specific(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    john = _person_with_addresses(migrated_db_session, JOHN)
    e6 = _email_and_chunk(
        migrated_db_session, source, from_handles=(JOHN,), to_handles=(MARY,)
    )
    e7 = _email_and_chunk(
        migrated_db_session,
        source,
        from_handles=(MARY,),
        to_handles=(MARY,),
        cc_handles=(JOHN,),
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="deny",
        roles=["cc"],
        person_id=john.id,
    )

    scope = _scope(migrated_engine, account.id)
    visible = _visible(migrated_engine, source, scope)
    assert e6.id in visible
    assert e7.id not in visible


def test_permit_narrows_to_matching_items(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    john = _person_with_addresses(migrated_db_session, JOHN)
    e6 = _email_and_chunk(
        migrated_db_session, source, from_handles=(JOHN,), to_handles=(MARY,)
    )
    e7 = _email_and_chunk(
        migrated_db_session, source, from_handles=(MARY,), to_handles=(MARY,)
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="permit",
        roles=["from"],
        person_id=john.id,
    )

    scope = _scope(migrated_engine, account.id)
    visible = _visible(migrated_engine, source, scope)
    assert e6.id in visible
    assert e7.id not in visible


def test_person_address_expansion_uses_current_directory(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    john = _person_with_addresses(migrated_db_session, JOHN, NEW_JOHN)
    e6 = _email_and_chunk(
        migrated_db_session, source, from_handles=(NEW_JOHN,), to_handles=(MARY,)
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="deny",
        roles=["from"],
        person_id=john.id,
    )

    scope = _scope(migrated_engine, account.id)
    assert e6.id not in _visible(migrated_engine, source, scope)


def test_date_and_direction_predicates(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    inside = _email_and_chunk(
        migrated_db_session,
        source,
        from_handles=(JOHN,),
        to_handles=(MARY,),
        sent_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
    outside = _email_and_chunk(
        migrated_db_session,
        source,
        from_handles=(JOHN,),
        to_handles=(MARY,),
        sent_at=datetime(2026, 2, 15, tzinfo=UTC),
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="deny",
        roles=["from"],
        person_id=None,
        addresses=[JOHN],
        extra_predicates=[
            {
                "operator": "date_range",
                "from": "2026-01-01",
                "to": "2026-02-01",
            },
            {"operator": "direction", "direction": "received"},
        ],
    )

    scope = _scope(migrated_engine, account.id)
    visible = _visible(migrated_engine, source, scope)
    assert inside.id not in visible
    assert outside.id in visible


def test_l2_verifier_uses_reference_evaluator(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    john = _person_with_addresses(migrated_db_session, JOHN)
    e6 = _email_and_chunk(
        migrated_db_session, source, from_handles=(JOHN,), to_handles=(MARY,)
    )
    e7 = _email_and_chunk(
        migrated_db_session, source, from_handles=(MARY,), to_handles=(MARY,)
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="deny",
        roles=["from"],
        person_id=john.id,
    )

    scope = _scope(migrated_engine, account.id)
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    verifier = PostgresAccessVerifier(factory)
    visible = asyncio.run(
        verifier.visible_item_ids(_plan(account.id, source, scope), (e6.id, e7.id))
    )
    assert visible == frozenset({e7.id})


def test_invalid_active_policy_fails_closed(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    policy = PolicyModel(
        account_id=account.id,
        title="broken",
        principal_kind="all_agents",
        policy_type="access",
        status="active",
        current_revision=1,
    )
    migrated_db_session.add(policy)
    migrated_db_session.flush()
    migrated_db_session.add(
        PolicyRevisionModel(
            policy_id=policy.id,
            revision=1,
            spec={"type": "access", "unexpected": True},
            source_encrypted="test",
            interpreter_version="test",
            model_id="test",
        )
    )
    migrated_db_session.commit()

    with pytest.raises(AccessPolicyError):
        asyncio.run(_repo(migrated_engine).load_access_policies(account.id))


def test_no_policies_is_permit_all(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    message = _email_and_chunk(
        migrated_db_session, source, from_handles=(JOHN,), to_handles=(MARY,)
    )
    migrated_db_session.commit()
    scope = _scope(migrated_engine, account.id)
    assert message.id in _visible(migrated_engine, source, scope)


def test_lexical_level_gate_changes_sql(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    john = _person_with_addresses(migrated_db_session, JOHN)
    denied = _email_and_chunk(
        migrated_db_session, source, from_handles=(JOHN,), to_handles=(MARY,)
    )
    visible = _email_and_chunk(
        migrated_db_session, source, from_handles=(MARY,), to_handles=(MARY,)
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="deny",
        roles=["from"],
        person_id=john.id,
    )
    scope = _scope(migrated_engine, account.id)
    plan = _plan(account.id, source, scope)

    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    with factory() as session:
        filtered = set(
            session.scalars(
                select(models.Chunk.email_id).where(
                    models.Chunk.source_account_id == source.id,
                    *filter_conditions(plan, apply_access=True),
                )
            )
        )
        unfiltered = set(
            session.scalars(
                select(models.Chunk.email_id).where(
                    models.Chunk.source_account_id == source.id,
                    *filter_conditions(plan, apply_access=False),
                )
            )
        )

    assert filtered == {visible.id}
    assert unfiltered == {denied.id, visible.id}


def test_metadata_level_gate_changes_coverage(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    john = _person_with_addresses(migrated_db_session, JOHN)
    _email_and_chunk(
        migrated_db_session,
        source,
        from_handles=(JOHN,),
        to_handles=(MARY,),
        sent_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    visible_at = datetime(2026, 3, 1, tzinfo=UTC)
    _email_and_chunk(
        migrated_db_session,
        source,
        from_handles=(MARY,),
        to_handles=(MARY,),
        sent_at=visible_at,
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="deny",
        roles=["from"],
        person_id=john.id,
    )
    scope = _scope(migrated_engine, account.id)
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    repo = PostgresSearchRepository(factory)

    filtered = asyncio.run(
        repo.get_metadata(frozenset({source.id}), access_scope=scope, apply_access=True)
    )
    unfiltered = asyncio.run(
        repo.get_metadata(
            frozenset({source.id}), access_scope=scope, apply_access=False
        )
    )

    assert filtered.min_sent_at == visible_at
    assert unfiltered.min_sent_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_thread_level_gate_changes_resolution(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    john = _person_with_addresses(migrated_db_session, JOHN)
    thread = models.EmailThread(
        id=uuid.uuid4(), source_account_id=source.id, root_message_id="root"
    )
    migrated_db_session.add(thread)
    migrated_db_session.flush()
    denied = _email_and_chunk(
        migrated_db_session,
        source,
        from_handles=(JOHN,),
        to_handles=(MARY,),
        thread_id=thread.id,
    )
    _add_policy(
        migrated_db_session,
        account.id,
        effect="deny",
        roles=["from"],
        person_id=john.id,
    )
    scope = _scope(migrated_engine, account.id)
    search_scope = Scope(
        account_id=account.id, source_account_ids=frozenset({source.id})
    )
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    repo = PostgresSearchRepository(factory)

    assert (
        asyncio.run(
            repo.resolve_thread(
                search_scope,
                denied.id,
                access_scope=scope,
                apply_access=True,
            )
        )
        is None
    )
    assert (
        asyncio.run(
            repo.resolve_thread(
                search_scope,
                denied.id,
                access_scope=scope,
                apply_access=False,
            )
        )
        == thread.id
    )


def test_levels_change_the_plan_fingerprint(
    migrated_engine, migrated_uow, migrated_db_session
) -> None:
    from tests._account import ensure_account

    account = ensure_account(migrated_uow)
    source = _source(migrated_db_session, account.id, "in-scope")
    scope = _scope(migrated_engine, account.id)
    plan = _plan(account.id, source, scope)
    changed = replace(plan, access_levels=AccessEnforcementLevels(lexical=False))
    assert plan.fingerprint != changed.fingerprint
