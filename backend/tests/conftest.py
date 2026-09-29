from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.community.postgres import PostgresContainer

from rosalind import config
from rosalind.adapters.composition import (
    build_person_service,
    get_person_service,
    get_uow,
)
from rosalind.adapters.inbound.http.app import app
from rosalind.adapters.outbound.persistence.models import Base
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application.services.people import PersonService
from tests._db import make_migrated_engine, reset_schemas


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch) -> None:
    monkeypatch.setattr(
        config.settings, "token_encryption_key", Fernet.generate_key().decode()
    )


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    try:
        container = PostgresContainer("postgres:18", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - skip if Docker is unavailable
        pytest.skip(f"Docker unavailable: {exc}")
        return ""

    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def _make_engine(url: str) -> Engine:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS agent"))
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def db_session(postgres_url: str) -> Iterator[Session]:
    engine = _make_engine(postgres_url)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def uow(db_session: Session) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(db_session)


@pytest.fixture()
def api_client(postgres_url: str):
    engine = _make_engine(postgres_url)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_uow() -> Iterator[SqlAlchemyUnitOfWork]:
        with factory() as session:
            yield SqlAlchemyUnitOfWork(session)

    def override_get_person_service() -> Iterator[PersonService]:
        with factory() as session:
            yield build_person_service(session)

    app.dependency_overrides[get_uow] = override_get_uow
    app.dependency_overrides[get_person_service] = override_get_person_service
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def migrated_engine(postgres_url: str) -> Iterator[Engine]:
    """An engine whose schema is built by real Alembic migrations.

    Reset before and after each test so views such as ``agent.person_profile``
    exist and the shared container stays clean.
    """
    engine = make_migrated_engine(postgres_url)
    try:
        yield engine
    finally:
        reset_schemas(engine)
        engine.dispose()


@pytest.fixture()
def migrated_db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A session against the real Alembic-migrated database."""
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def migrated_uow(migrated_db_session: Session) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(migrated_db_session)


@pytest.fixture()
def migrated_api_client(migrated_engine: Engine):
    """A TestClient backed by the real Alembic-migrated database."""
    factory = sessionmaker(
        bind=migrated_engine, autoflush=False, expire_on_commit=False
    )

    def override_get_uow() -> Iterator[SqlAlchemyUnitOfWork]:
        with factory() as session:
            yield SqlAlchemyUnitOfWork(session)

    def override_get_person_service() -> Iterator[PersonService]:
        with factory() as session:
            yield build_person_service(session)

    app.dependency_overrides[get_uow] = override_get_uow
    app.dependency_overrides[get_person_service] = override_get_person_service
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
