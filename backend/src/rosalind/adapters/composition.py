"""Composition root: wire application services to concrete adapters.

This is the only place concrete adapter implementations are selected. Application
services and ports never import these concrete classes. Both the HTTP and MCP
adapters (and tests) build their service graph from here.
"""

from __future__ import annotations

from rosalind.adapters.inbound.ingestion.google.parser import GooglePersonParser
from rosalind.adapters.outbound.google.auth import GoogleAuthGateway
from rosalind.adapters.outbound.google.people import GooglePeopleGateway
from rosalind.application.canonicalization.person import CanonicalizationService
from rosalind.application.services.processing import ProcessingService
from rosalind.application.services.sources import SourceService

google_auth = GoogleAuthGateway()
google_people = GooglePeopleGateway()

source_service = SourceService(google_auth)

_google_person_parser = GooglePersonParser()

processing_service = ProcessingService(
    parsers={_google_person_parser.resource_type: _google_person_parser},
    person_parser=_google_person_parser,
    people=google_people,
    sources=source_service,
    canonicalizer=CanonicalizationService(),
)
