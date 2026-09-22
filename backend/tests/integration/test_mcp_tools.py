import asyncio
import json
import uuid
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

import rosalind.adapters.inbound.mcp.server as mcp_server
from rosalind.adapters import composition
from rosalind.adapters.inbound.mcp.schemas import PersonProfileResult
from rosalind.adapters.outbound.persistence import models

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "google" / "person_profile.json"
)


def _ingest(engine: Engine) -> uuid.UUID:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        account = models.SourceAccount(
            provider="google", account_identifier="test-account"
        )
        db.add(account)
        db.commit()
        result = composition.processing_service.ingest_person(
            db, account, json.loads(FIXTURE.read_text())
        )
        return result.person_id


def test_mcp_tools_share_person_service(migrated_engine: Engine, monkeypatch) -> None:
    person_id = _ingest(migrated_engine)
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(mcp_server, "SessionLocal", factory)

    results = mcp_server.search_people("Alex")
    assert len(results) == 1
    assert isinstance(results[0], PersonProfileResult)
    assert results[0].display_name == "Alex Morgan"

    profile = mcp_server.get_person(person_id)
    assert isinstance(profile, PersonProfileResult)
    assert profile.primary_email == "alex.morgan@example.com"

    assert mcp_server.get_person(uuid.uuid4()) is None


def test_mcp_get_person_rejects_malformed_id() -> None:
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.mcp.call_tool("get_person", {"person_id": "not-a-uuid"}))
