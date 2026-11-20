import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

import rosalind.adapters.inbound.mcp.server as mcp_server
from rosalind import config
from rosalind.adapters import composition
from rosalind.adapters.inbound.mcp.schemas import (
    MyProfileResult,
    PersonProfileResult,
    SearchResult,
)
from rosalind.adapters.inbound.mcp.search import SearchEmailsInput
from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.policy.adapters.persistence import (
    PolicyModel,
    PolicyRevisionModel,
    PolicyVersionModel,
)
from tests._account import TEST_ISSUER, TEST_SUBJECT, ensure_account

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "google" / "person_profile.json"
)


def _ingest(engine: Engine) -> uuid.UUID:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        uow = SqlAlchemyUnitOfWork(db)
        account_id = ensure_account(uow).id
        account = composition.source_service.create_source(
            uow, account_id, provider="google", name="test-account"
        )
        result = composition.processing_service.ingest_person(
            uow, account, json.loads(FIXTURE.read_text())
        )
        return result.person_id


def _test_token() -> AccessToken:
    return AccessToken(
        token="t",
        client_id="rosalind-cli",
        scopes=["openid"],
        subject=TEST_SUBJECT,
        claims={
            "iss": TEST_ISSUER,
            "email": "jane@example.com",
            "preferred_username": "jane@example.com",
            "given_name": "Jane",
            "family_name": "Doe",
        },
    )


def test_mcp_tools_share_person_service(migrated_engine: Engine, monkeypatch) -> None:
    person_id = _ingest(migrated_engine)
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(mcp_server, "SessionLocal", factory)

    reset = auth_context_var.set(AuthenticatedUser(_test_token()))
    try:
        results = mcp_server.search_people("Alex")
        assert len(results) == 1
        assert isinstance(results[0], PersonProfileResult)
        assert results[0].display_name == "Alex Morgan"

        profile = mcp_server.get_person(person_id)
        assert isinstance(profile, PersonProfileResult)
        assert profile.primary_email == "alex.morgan@example.com"

        assert mcp_server.get_person(uuid.uuid4()) is None
    finally:
        auth_context_var.reset(reset)


def test_mcp_person_tools_return_empty_without_account(
    migrated_engine: Engine, monkeypatch
) -> None:
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(mcp_server, "SessionLocal", factory)

    assert mcp_server.search_people("Alex") == []
    assert mcp_server.get_person(uuid.uuid4()) is None


def test_mcp_get_person_rejects_malformed_id() -> None:
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.mcp.call_tool("get_person", {"person_id": "not-a-uuid"}))


def test_get_my_profile(migrated_engine: Engine, monkeypatch) -> None:
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(mcp_server, "SessionLocal", factory)

    token = AccessToken(
        token="t",
        client_id="rosalind-cli",
        scopes=["openid"],
        subject="user-1",
        claims={
            "iss": "http://localhost:8080/realms/rosalind",
            "email": "jane@example.com",
            "preferred_username": "jane@example.com",
            "given_name": "Jane",
            "family_name": "Doe",
        },
    )
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        result = mcp_server.get_my_profile()
    finally:
        auth_context_var.reset(reset)

    assert isinstance(result, MyProfileResult)
    assert result.email == "jane@example.com"
    assert result.given_name == "Jane"
    assert result.family_name == "Doe"
    assert result.account_id is not None


def test_get_my_profile_returns_none_without_token() -> None:
    assert mcp_server.get_my_profile() is None


def test_search_tool_rejects_malformed_input() -> None:
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.mcp.call_tool("search", {"input": {"limit": 999}}))


def test_search_tool_rejects_unknown_field() -> None:
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.mcp.call_tool("search", {"input": {"bogus": 1}}))


def test_search_tool_returns_empty_scope_without_data(
    migrated_engine: Engine, monkeypatch
) -> None:
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(mcp_server, "SessionLocal", factory)

    reset = auth_context_var.set(AuthenticatedUser(_test_token()))
    try:
        result = asyncio.run(
            mcp_server.search(SearchEmailsInput(query="holidays in Spain"))
        )
    finally:
        auth_context_var.reset(reset)

    assert isinstance(result, SearchResult)
    assert result.short_circuit == "empty_scope"


def test_search_access_enforcement_flag(migrated_engine: Engine, monkeypatch) -> None:
    """The setting gates real access filtering without a restart in tests."""
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    john = "john.smith@acme.com"
    mary = "mary@example.com"
    sent_at = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)

    with factory() as db:
        uow = SqlAlchemyUnitOfWork(db)
        account = ensure_account(uow)
        source = models.SourceAccount(
            account_id=account.id, provider="google", name="enforcement-test"
        )
        db.add(source)
        db.flush()

        message = models.EmailMessage(
            id=uuid.uuid4(),
            source_account_id=source.id,
            message_id="enforcement-message",
            message_id_synthetic=False,
            occurred_at=sent_at,
            direction="received",
            subject="Quarterly update",
            has_attachments=False,
            is_trash_or_spam=False,
            parser_version="p/1",
            canonicalizer_version="c/1",
            metadata_={},
        )
        db.add(message)
        db.flush()
        db.add(
            models.Chunk(
                id=uuid.uuid4(),
                email_id=message.id,
                chunk_kind="email_body",
                seq=0,
                text_for_display="quarterly canary numbers",
                text_for_index="quarterly canary numbers",
                text_sha256="enforcement-canary",
                language="en",
                index_version="v1",
                source_account_id=source.id,
                source_account_num=source.num,
                sent_at=sent_at,
                sender_handle=john,
                recipient_handles=[mary],
                participant_handles=sorted([john, mary]),
                from_handles=[john],
                to_handles=[mary],
                cc_handles=[],
                bcc_handles=[],
                direction="received",
                has_attachment=False,
                is_trash_or_spam=False,
                tags=[],
                meta={},
            )
        )

        policy = PolicyModel(
            account_id=account.id,
            title="deny john",
            principal_kind="all_agents",
            policy_type="access",
            status="active",
            current_revision=1,
        )
        db.add(policy)
        db.flush()
        db.add(
            PolicyRevisionModel(
                policy_id=policy.id,
                revision=1,
                spec={
                    "schema_version": "rosalind.policy.v2",
                    "type": "access",
                    "effect": "deny",
                    "principal": {"type": "all_agents"},
                    "resource": {
                        "type": "email",
                        "selector": {
                            "operator": "all_of",
                            "predicates": [
                                {
                                    "operator": "has_participant",
                                    "roles": ["from"],
                                    "addresses": [john],
                                }
                            ],
                        },
                    },
                    "status": "active",
                },
                source_encrypted="test",
                interpreter_version="test",
                model_id="test",
            )
        )
        db.add(PolicyVersionModel(account_id=account.id, version=1))
        db.commit()
        message_id = message.id

    monkeypatch.setattr(mcp_server, "SessionLocal", factory)
    reset = auth_context_var.set(AuthenticatedUser(_test_token()))
    try:
        monkeypatch.setattr(config.settings.policy, "access_enforcement_enabled", False)
        off = asyncio.run(
            mcp_server.search(SearchEmailsInput(query="canary", mode="lexical"))
        )
        assert off is not None
        assert [result.item_id for result in off.results] == [message_id]

        monkeypatch.setattr(config.settings.policy, "access_enforcement_enabled", True)
        on = asyncio.run(
            mcp_server.search(SearchEmailsInput(query="canary", mode="lexical"))
        )
        assert on is not None
        assert on.results == []
    finally:
        auth_context_var.reset(reset)
