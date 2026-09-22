"""Import lifecycle and processing endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from rosalind import config
from rosalind.adapters import composition
from rosalind.adapters.inbound.http.schemas import imports as schemas
from rosalind.adapters.outbound.object_storage import s3
from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.session import get_db
from rosalind.application import manifest
from rosalind.application.services import imports as imports_service
from rosalind.application.services.processing import PROCESSING_COMPLETED

router = APIRouter(prefix="/imports", tags=["imports"])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=schemas.ImportListResponse)
def list_imports(db: SessionDep) -> schemas.ImportListResponse:
    imports = imports_service.list_imports(db)
    return schemas.ImportListResponse(
        imports=[_to_summary(import_) for import_ in imports]
    )


@router.post(
    "",
    response_model=schemas.ImportCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_import(
    body: schemas.ImportCreateRequest,
    db: SessionDep,
) -> schemas.ImportCreatedResponse:
    source = composition.source_service.resolve_source(db, body.source_name)

    if body.type == imports_service.IMPORT_TYPE_TAKEOUT:
        import_ = imports_service.create_import(db, source, body.type)
    elif body.type == imports_service.IMPORT_TYPE_API:
        import_ = imports_service.create_import(db, source, body.type)
        composition.processing_service.import_api_profile(db, source, import_)
        import_.ingestion_status = imports_service.INGESTION_COMPLETED
        import_.processing_status = PROCESSING_COMPLETED
        db.commit()
        db.refresh(import_)
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported import type {body.type!r}",
        )

    return schemas.ImportCreatedResponse(
        import_id=import_.id,
        source_id=import_.source_account_id,
        source_name=source.name,
        type=import_.type,
        bucket=config.settings.s3_bucket,
        storage_prefix=manifest.storage_prefix(import_.id),
        ingestion_status=import_.ingestion_status,
        processing_status=import_.processing_status,
    )


@router.post(
    "/{import_id}/complete",
    response_model=schemas.ImportSummaryResponse,
)
def complete_import(
    import_id: uuid.UUID,
    body: schemas.ManifestRequest,
    db: SessionDep,
) -> schemas.ImportSummaryResponse:
    entries = [
        manifest.FileEntry(
            path=f.path,
            sha256=f.sha256,
            size=f.size,
            format=f.format,
            modified_at=f.modified_at,
        )
        for f in body.files
    ]
    import_ = imports_service.complete_import(db, import_id, entries)
    return _to_summary(import_)


@router.post(
    "/{import_id}/process",
    response_model=schemas.ProcessingResultResponse,
)
def process_import(
    import_id: uuid.UUID,
    db: SessionDep,
) -> schemas.ProcessingResultResponse:
    outcome = composition.processing_service.process_import(db, import_id)
    return schemas.ProcessingResultResponse(
        import_id=import_id,
        processing_status=_processing_status(db, import_id),
        result=outcome.result,
        message=outcome.message,
        people_created=outcome.people_created,
        facts_created=outcome.facts_created,
        facts_reused=outcome.facts_reused,
        assertions_created=outcome.assertions_created,
    )


@router.get(
    "/{import_id}",
    response_model=schemas.ImportDetailResponse,
)
def get_import(
    import_id: uuid.UUID,
    db: SessionDep,
) -> schemas.ImportDetailResponse:
    import_ = imports_service.get_import(db, import_id)
    return schemas.ImportDetailResponse(
        **_to_summary(import_).model_dump(),
        files=[_to_file(f) for f in import_.files],
    )


@router.delete(
    "/{import_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_import(
    import_id: uuid.UUID,
    db: SessionDep,
) -> Response:
    import_ = imports_service.get_import(db, import_id)
    s3.delete_objects(config.settings.s3_bucket, [f.storage_key for f in import_.files])
    imports_service.delete_import(db, import_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _processing_status(db: Session, import_id: uuid.UUID) -> str:
    import_ = imports_service.get_import(db, import_id)
    return import_.processing_status


def _to_summary(import_: models.Import) -> schemas.ImportSummaryResponse:
    source = import_.source_account
    return schemas.ImportSummaryResponse(
        import_id=import_.id,
        source_id=import_.source_account_id,
        source_name=source.name if source else None,
        type=import_.type,
        ingestion_status=import_.ingestion_status,
        processing_status=import_.processing_status,
        created_at=import_.created_at,
        completed_at=import_.completed_at,
        file_count=import_.file_count,
        total_size=import_.total_size,
        import_hash=import_.import_hash,
    )


def _to_file(file_: models.ImportFile) -> schemas.FileResponse:
    return schemas.FileResponse(
        path=file_.path,
        sha256=file_.sha256,
        size=file_.size,
        format=file_.format,
        modified_at=file_.modified_at,
        storage_key=file_.storage_key,
    )
