"""Database engine, session factory, and FastAPI dependencies."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rosalind import config
from rosalind.adapters.outbound.persistence.repositories.person import (
    PostgresPersonRepository,
)
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.services.people import PersonService

engine = create_engine(config.settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_uow() -> Iterator[UnitOfWork]:
    """Provide a transaction-scoped unit of work for a request.

    Explicitly rolls back on exception and always closes the session, rather
    than relying on pool-level connection reset behavior.
    """
    session = SessionLocal()
    try:
        yield SqlAlchemyUnitOfWork(session)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_person_service() -> Iterator[PersonService]:
    """Provide a session-bound read-only person service for a request."""
    with SessionLocal() as session:
        yield PersonService(PostgresPersonRepository(session))
