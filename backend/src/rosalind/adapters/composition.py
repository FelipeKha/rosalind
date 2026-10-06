"""Composition root: wire application services to concrete adapters.

This is the only place concrete adapter implementations are selected. Application
services and ports never import these concrete classes. Both the HTTP and MCP
adapters (and tests) build their service graph from here.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from rosalind.adapters.inbound.ingestion.google.parser import GooglePersonParser
from rosalind.adapters.outbound.enrichment.html import SelectolaxHtmlParser
from rosalind.adapters.outbound.enrichment.language import LinguaLanguageDetector
from rosalind.adapters.outbound.google.auth import GoogleAuthGateway
from rosalind.adapters.outbound.google.people import GooglePeopleGateway
from rosalind.adapters.outbound.keycloak.jwt import KeycloakJwtVerifier
from rosalind.adapters.outbound.object_storage.s3 import S3ObjectStorage
from rosalind.adapters.outbound.persistence.embedding_spaces import embedding_space
from rosalind.adapters.outbound.persistence.repositories.person import (
    PostgresPersonRepository,
)
from rosalind.adapters.outbound.persistence.session import SessionLocal
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.adapters.outbound.search.embedder_tei import TeiEmbedder
from rosalind.adapters.outbound.search.tokenizer import BgeM3TokenCounter
from rosalind.application.canonicalization.email_message import (
    EmailCanonicalizationService,
)
from rosalind.application.canonicalization.person import CanonicalizationService
from rosalind.application.ports.identity import TokenVerifier
from rosalind.application.ports.object_storage import ObjectStorage
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.services.accounts import AccountService
from rosalind.application.services.attachment_extraction import (
    AttachmentExtractionService,
)
from rosalind.application.services.chunking import EmailChunkingService
from rosalind.application.services.email_reconciliation import (
    EmailReconciliationService,
)
from rosalind.application.services.emails import EmailProcessingService
from rosalind.application.services.embedding import EmailEmbeddingService
from rosalind.application.services.enrichment import EmailEnrichmentService
from rosalind.application.services.imports import ImportService
from rosalind.application.services.people import PersonService
from rosalind.application.services.processing import ProcessingService
from rosalind.application.services.search import SearchService
from rosalind.application.services.sources import SourceService
from rosalind.config import settings
from rosalind.domain.search import ChunkingParams

google_auth = GoogleAuthGateway()
google_people = GooglePeopleGateway()

object_storage = S3ObjectStorage()

source_service = SourceService(google_auth)

account_service = AccountService()

token_verifier: TokenVerifier = KeycloakJwtVerifier()

search_service = SearchService()

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

attachment_extraction_service = AttachmentExtractionService(
    storage=object_storage,
    max_bytes=settings.attachment_max_bytes,
    max_output_chars=settings.attachment_max_output_chars,
    timeout_seconds=settings.attachment_timeout_seconds,
)

chunking_service = EmailChunkingService(
    counter=BgeM3TokenCounter(
        settings.chunk_tokenizer_path,
        settings.chunk_tokenizer_sha256,
    ),
    params=ChunkingParams(
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        min_tail_tokens=settings.chunk_min_tail_tokens,
        max_quote_tokens_per_email=settings.chunk_max_quote_tokens_per_email,
        max_chunks_per_attachment=settings.chunk_max_chunks_per_attachment,
        include_signature=settings.chunk_include_signature,
    ),
    limit=settings.chunk_batch_size,
)

_token_counter = BgeM3TokenCounter(
    settings.chunk_tokenizer_path,
    settings.chunk_tokenizer_sha256,
)

embedding_service: EmailEmbeddingService | None = None
if settings.embedder_url:
    space = embedding_space(settings.embedding_space)
    embedder = TeiEmbedder(
        settings.embedder_url,
        space,
        timeout=settings.embed_timeout,
        concurrency=settings.embed_concurrency,
        retries=settings.embed_retries,
    )
    embedding_service = EmailEmbeddingService(
        embedder,
        _token_counter,
        embed_quotes=settings.embed_quotes,
        embed_trash_spam=settings.embed_trash_spam,
        allow_remote_embedding=settings.allow_remote_embedding,
        window=settings.embed_window,
        batch_tokens=settings.embed_batch_tokens,
    )

email_processing_service = EmailProcessingService(
    storage=object_storage,
    canonicalizer=EmailCanonicalizationService(),
    reconciler=EmailReconciliationService(),
    enrich_budget_seconds=settings.enrich_budget_seconds,
    enrich_batch_size=settings.enrich_batch_size,
    enricher=EmailEnrichmentService(
        html_parser=SelectolaxHtmlParser(),
        detector=LinguaLanguageDetector(
            languages=tuple(settings.enrich_languages),
            min_confidence=settings.enrich_language_min_confidence,
        ),
        min_language_length=settings.enrich_min_language_length,
    ),
    attachment_extractor=attachment_extraction_service,
    attachment_budget_seconds=settings.attachment_budget_seconds,
    chunker=chunking_service,
    embedder=embedding_service,
    embed_inline_budget_seconds=settings.embed_inline_budget_seconds,
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


def get_source_service() -> SourceService:
    return source_service


def get_account_service() -> AccountService:
    return account_service


def get_search_service() -> SearchService:
    return search_service


def get_token_verifier() -> TokenVerifier:
    return token_verifier


def get_processing_service() -> ProcessingService:
    return processing_service


def get_import_service() -> ImportService:
    return import_service


def get_email_processing_service() -> EmailProcessingService:
    return email_processing_service


def get_attachment_extraction_service() -> AttachmentExtractionService:
    return attachment_extraction_service


def get_object_storage() -> ObjectStorage:
    return object_storage
