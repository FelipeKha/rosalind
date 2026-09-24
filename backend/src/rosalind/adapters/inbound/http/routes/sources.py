"""Source endpoints: list, show, create, connect, and disconnect."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from rosalind.adapters.composition import get_source_service, get_uow
from rosalind.adapters.inbound.http.schemas import sources as schemas
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.services.sources import (
    SOURCE_CONNECTED,
    SOURCE_DISCONNECTED,
    SourceService,
)
from rosalind.domain.source import SourceAccount

router = APIRouter(prefix="/sources", tags=["sources"])

UowDep = Annotated[UnitOfWork, Depends(get_uow)]
SourceDep = Annotated[SourceService, Depends(get_source_service)]


@router.get("", response_model=schemas.SourceListResponse)
def list_sources(uow: UowDep, service: SourceDep) -> schemas.SourceListResponse:
    return schemas.SourceListResponse(
        sources=[
            _to_summary(source, uow, service) for source in service.list_sources(uow)
        ]
    )


@router.post(
    "",
    response_model=schemas.SourceSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source(
    body: schemas.SourceCreateRequest,
    uow: UowDep,
    service: SourceDep,
) -> schemas.SourceSummaryResponse:
    source = service.create_source(uow, provider=body.provider, name=body.name)
    return _to_summary(source, uow, service)


@router.post("/connect", response_model=schemas.ConnectResponse)
def connect(
    body: schemas.SourceConnectRequest,
    uow: UowDep,
    service: SourceDep,
) -> schemas.ConnectResponse:
    result = service.start_connect(uow, provider=body.provider, name=body.name)
    return schemas.ConnectResponse(
        source_id=result.source_id,
        auth_url=result.auth_url,
        state=result.state,
    )


@router.get("/connect/status", response_model=schemas.ConnectStatusResponse)
def connect_status(
    state: str, uow: UowDep, service: SourceDep
) -> schemas.ConnectStatusResponse:
    result = service.get_connect_status(uow, state)
    return schemas.ConnectStatusResponse(
        status=result.status,
        source_id=result.source_id,
        display_name=result.display_name,
    )


@router.get("/{source_id}", response_model=schemas.SourceDetailResponse)
def get_source(
    source_id: uuid.UUID, uow: UowDep, service: SourceDep
) -> schemas.SourceDetailResponse:
    source = service.get_source(uow, source_id)
    return _to_detail(source, uow, service)


@router.post(
    "/{source_id}/disconnect",
    response_model=schemas.DisconnectResponse,
)
def disconnect(
    source_id: uuid.UUID, uow: UowDep, service: SourceDep
) -> schemas.DisconnectResponse:
    result = service.disconnect(uow, source_id)
    return schemas.DisconnectResponse(status=result.status, revoked=result.revoked)


def _to_summary(
    source: SourceAccount, uow: UnitOfWork, service: SourceService
) -> schemas.SourceSummaryResponse:
    return schemas.SourceSummaryResponse(
        source_id=source.id,
        name=source.name,
        provider=source.provider,
        display_name=source.display_name,
        status=_status(source, uow, service),
        created_at=source.created_at,
    )


def _to_detail(
    source: SourceAccount, uow: UnitOfWork, service: SourceService
) -> schemas.SourceDetailResponse:
    return schemas.SourceDetailResponse(
        source_id=source.id,
        name=source.name,
        provider=source.provider,
        display_name=source.display_name,
        status=_status(source, uow, service),
        created_at=source.created_at,
        account_identifier=source.account_identifier,
    )


def _status(source: SourceAccount, uow: UnitOfWork, service: SourceService) -> str:
    return (
        SOURCE_CONNECTED
        if service.is_connected(uow, source.id)
        else SOURCE_DISCONNECTED
    )
