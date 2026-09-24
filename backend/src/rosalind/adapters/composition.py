"""Composition root: wire application services to concrete adapters.

This is the only place concrete adapter implementations are selected. Application
services and ports never import these concrete classes. Both the HTTP and MCP
adapters (and tests) build their service graph from here.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from rosalind.adapters.inbound.ingestion.google.parser import GooglePersonParser
from rosalind.adapters.outbound.google.auth import GoogleAuthGateway
from rosalind.adapters.outbound.google.people import GooglePeopleGateway
from rosalind.adapters.outbound.object_storage.s3 import S3ObjectStorage
from rosalind.adapters.outbound.persistence.repositories.person import (
    PostgresPersonRepository,
)
from rosalind.adapters.outbound.persistence.session import SessionLocal
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application.canonicalization.person import CanonicalizationService
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.services.imports import ImportService
from rosalind.application.services.people import PersonService
from rosalind.application.services.processing import ProcessingService
from rosalind.application.services.sources import SourceService

google_auth = GoogleAuthGateway()
google_people = GooglePeopleGateway()

object_storage = S3ObjectStorage()

source_service = SourceService(google_auth)

_google_person_parser = GooglePersonParser()

processing_service = ProcessingService(
    parsers={_google_person_parser.resource_type: _google_person_parser},
    person_parser=_google_person_parser,
    people=google_people,
    sources=source_service,
    canonicalizer=CanonicalizationService(),
)

import_service = ImportService(
    storage=object_storage,
    sources=source_service,
    processing=processing_service,
)


def build_person_service(session: Session) -> PersonService:
    return PersonService(PostgresPersonRepository(session))


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
        yield build_person_service(session)
