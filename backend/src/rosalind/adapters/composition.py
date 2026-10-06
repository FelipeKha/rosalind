"""Composition root: wire application services to concrete adapters.

This is the only place concrete adapter implementations are selected. Application
services and ports never import these concrete classes. Both the HTTP and MCP
adapters (and tests) build their service graph from here.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterator

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
from rosalind.adapters.outbound.search.audit import LoggingAudit
from rosalind.adapters.outbound.search.embedder_tei import TeiEmbedder
from rosalind.adapters.outbound.search.query_embedder import NullEmbedder, QueryEmbedder
from rosalind.adapters.outbound.search.search_repository import PostgresSearchRepository
from rosalind.adapters.outbound.search.tokenizer import BgeM3TokenCounter
from rosalind.application.canonicalization.email_message import (
    EmailCanonicalizationService,
)
from rosalind.application.canonicalization.person import CanonicalizationService
from rosalind.application.ports.identity import TokenVerifier
from rosalind.application.ports.object_storage import ObjectStorage
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.search import Budgets, FusionConfig, FusionStrategy
from rosalind.application.search.cursor import HmacCursorCodec
from rosalind.application.search.ports import SearchConfig
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


def _cursor_signing_key() -> bytes:
    if settings.search_cursor_key:
        return settings.search_cursor_key.encode("utf-8")
    if settings.token_encryption_key:
        material = f"rosalind-search-cursor:{settings.token_encryption_key}"
        return hashlib.sha256(material.encode("utf-8")).digest()
    logging.getLogger(__name__).warning(
        "no cursor signing key configured; using an insecure development key"
    )
    return b"rosalind-dev-cursor-signing-key"


def _search_config() -> SearchConfig:
    if settings.embedder_url:
        space = embedding_space(settings.embedding_space)
        embedding_model = space.model_id
        embedding_version = space.revision or space.name
    else:
        embedding_model = None
        embedding_version = None
    return SearchConfig(
        index_version=settings.search_index_version,
        embedding_model=embedding_model,
        embedding_version=embedding_version,
        reranker=settings.search_reranker,
        budgets=Budgets(
            lexical_k=settings.search_lexical_k,
            semantic_k=settings.search_semantic_k,
            fused_k=settings.search_fused_k,
            rerank_k=settings.search_rerank_k,
            window_k=settings.search_window_k,
        ),
        fusion=FusionConfig(
            strategy=FusionStrategy.RRF,
            rrf_k=settings.search_rrf_k,
            lexical_weight=settings.search_lexical_weight,
            semantic_weight=settings.search_semantic_weight,
            max_chunks_per_item=settings.search_max_chunks_per_item,
        ),
        max_query_chars=settings.search_max_query_chars,
        max_list_values=settings.search_max_list_values,
        default_timezone=settings.search_default_timezone,
    )


google_auth = GoogleAuthGateway()
google_people = GooglePeopleGateway()

object_storage = S3ObjectStorage()

source_service = SourceService(google_auth)

account_service = AccountService()

token_verifier: TokenVerifier = KeycloakJwtVerifier()

search_audit = LoggingAudit()

_search_cursor_codec = HmacCursorCodec(_cursor_signing_key())

_search_embedder: NullEmbedder | QueryEmbedder = NullEmbedder()

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
    _search_embedder = QueryEmbedder(embedder)

search_config = _search_config()

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


def build_search_service(session_factory: Callable[[], Session]) -> SearchService:
    """Wire the search service with a request-scoped session factory.

    Each port method opens its own short-lived session so Prepare's concurrent
    lookups never share a ``Session`` across threads. ``session_factory`` is
    supplied by the caller so tests can point it at a migrated engine.
    """
    repository = PostgresSearchRepository(session_factory)
    return SearchService(
        scope=repository,
        metadata=repository,
        entities=repository,
        threads=repository,
        embedder=_search_embedder,
        codec=_search_cursor_codec,
        audit=search_audit,
        config=search_config,
    )


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
