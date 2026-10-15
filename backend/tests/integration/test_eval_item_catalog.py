"""Integration test: resolving gold message ids against a real Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from rosalind.adapters import composition
from rosalind.adapters.outbound.eval.item_catalog import PostgresItemCatalog
from rosalind.adapters.outbound.persistence.models import EmailMessage, SourceAccount
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests._account import ensure_account


def _session_factory(session: Session):
    return sessionmaker(
        bind=session.get_bind(), autoflush=False, expire_on_commit=False
    )


def _message(source_account_id: uuid.UUID, message_id: str) -> EmailMessage:
    return EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source_account_id,
        message_id=message_id,
        occurred_at=datetime(2026, 3, 1, tzinfo=UTC),
        direction="received",
        parser_version="v1",
        canonicalizer_version="v1",
    )


def test_resolve_message_ids_maps_present_ids(db_session: Session) -> None:
    account = ensure_account(SqlAlchemyUnitOfWork(db_session))
    source = SourceAccount(account_id=account.id, provider="none", name="none")
    db_session.add(source)
    db_session.flush()

    first = _message(source.id, "msg-001@example.test")
    second = _message(source.id, "msg-002@example.test")
    db_session.add_all([first, second])
    db_session.commit()

    catalog = PostgresItemCatalog(_session_factory(db_session))
    resolved = catalog.resolve_message_ids(
        account.id, frozenset({"msg-001@example.test", "msg-missing@example.test"})
    )

    assert resolved == {"msg-001@example.test": str(first.id)}


def test_resolve_message_ids_is_scoped_to_account(db_session: Session) -> None:
    uow = SqlAlchemyUnitOfWork(db_session)
    account = ensure_account(uow)
    other = composition.account_service.get_or_create(
        uow, "http://test/realms/other", "other-subject"
    )
    uow.commit()

    source = SourceAccount(account_id=account.id, provider="none", name="none")
    other_source = SourceAccount(account_id=other.id, provider="other", name="other")
    db_session.add_all([source, other_source])
    db_session.flush()
    db_session.add(_message(source.id, "msg-001@example.test"))
    db_session.add(_message(other_source.id, "msg-009@example.test"))
    db_session.commit()

    catalog = PostgresItemCatalog(_session_factory(db_session))
    resolved = catalog.resolve_message_ids(
        account.id, frozenset({"msg-009@example.test"})
    )

    assert resolved == {}
