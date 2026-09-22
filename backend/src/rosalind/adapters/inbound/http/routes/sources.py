"""Source endpoints: list, show, create, connect, and disconnect."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from rosalind.adapters import composition
from rosalind.adapters.inbound.http.schemas import sources as schemas
from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.session import get_db
from rosalind.application.services.sources import SOURCE_CONNECTED, SOURCE_DISCONNECTED

router = APIRouter(prefix="/sources", tags=["sources"])

service = composition.source_service

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=schemas.SourceListResponse)
def list_sources(db: SessionDep) -> schemas.SourceListResponse:
    return schemas.SourceListResponse(
        sources=[_to_summary(source, db) for source in service.list_sources(db)]
    )


@router.post(
    "",
    response_model=schemas.SourceSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source(
    body: schemas.SourceCreateRequest,
    db: SessionDep,
) -> schemas.SourceSummaryResponse:
    source = service.create_source(db, provider=body.provider, name=body.name)
    return _to_summary(source, db)


@router.post("/connect", response_model=schemas.ConnectResponse)
def connect(
    body: schemas.SourceConnectRequest,
    db: SessionDep,
) -> schemas.ConnectResponse:
    result = service.start_connect(db, provider=body.provider, name=body.name)
    return schemas.ConnectResponse(
        source_id=result.source_id,
        auth_url=result.auth_url,
        state=result.state,
    )


@router.get("/connect/status", response_model=schemas.ConnectStatusResponse)
def connect_status(state: str, db: SessionDep) -> schemas.ConnectStatusResponse:
    result = service.get_connect_status(db, state)
    return schemas.ConnectStatusResponse(
        status=result.status,
        source_id=result.source_id,
        display_name=result.display_name,
    )


@router.get("/{source_id}", response_model=schemas.SourceDetailResponse)
def get_source(source_id: uuid.UUID, db: SessionDep) -> schemas.SourceDetailResponse:
    source = service.get_source(db, source_id)
    return _to_detail(source, db)


@router.post(
    "/{source_id}/disconnect",
    response_model=schemas.DisconnectResponse,
)
def disconnect(source_id: uuid.UUID, db: SessionDep) -> schemas.DisconnectResponse:
    result = service.disconnect(db, source_id)
    return schemas.DisconnectResponse(status=result.status, revoked=result.revoked)


def _to_summary(
    source: models.SourceAccount, db: Session
) -> schemas.SourceSummaryResponse:
    return schemas.SourceSummaryResponse(
        source_id=source.id,
        name=source.name,
        provider=source.provider,
        display_name=source.display_name,
        status=_status(source, db),
        created_at=source.created_at,
    )


def _to_detail(
    source: models.SourceAccount, db: Session
) -> schemas.SourceDetailResponse:
    return schemas.SourceDetailResponse(
        source_id=source.id,
        name=source.name,
        provider=source.provider,
        display_name=source.display_name,
        status=_status(source, db),
        created_at=source.created_at,
        account_identifier=source.account_identifier,
    )


def _status(source: models.SourceAccount, db: Session) -> str:
    return (
        SOURCE_CONNECTED if service.is_connected(db, source.id) else SOURCE_DISCONNECTED
    )
