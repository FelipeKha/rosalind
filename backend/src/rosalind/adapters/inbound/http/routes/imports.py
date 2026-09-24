"""Import lifecycle and processing endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from rosalind.adapters import composition
from rosalind.adapters.inbound.http.schemas import imports as schemas
from rosalind.adapters.outbound.persistence.session import get_uow
from rosalind.application import manifest
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.source import Import, ImportFile

router = APIRouter(prefix="/imports", tags=["imports"])

UowDep = Annotated[UnitOfWork, Depends(get_uow)]


@router.get("", response_model=schemas.ImportListResponse)
def list_imports(uow: UowDep) -> schemas.ImportListResponse:
    imports = composition.import_service.list_imports(uow)
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
    uow: UowDep,
) -> schemas.ImportCreatedResponse:
    import_ = composition.import_service.create_import(uow, body.source_name, body.type)
    return schemas.ImportCreatedResponse(
        import_id=import_.id,
        source_id=import_.source_account_id,
        source_name=import_.source_name,
        type=import_.type,
        bucket=composition.object_storage.bucket,
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
    uow: UowDep,
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
    import_ = composition.import_service.complete_import(uow, import_id, entries)
    return _to_summary(import_)


@router.post(
    "/{import_id}/process",
    response_model=schemas.ProcessingResultResponse,
)
def process_import(
    import_id: uuid.UUID,
    uow: UowDep,
) -> schemas.ProcessingResultResponse:
    outcome = composition.processing_service.process_import(uow, import_id)
    return schemas.ProcessingResultResponse(
        import_id=import_id,
        processing_status=outcome.processing_status,
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
    uow: UowDep,
) -> schemas.ImportDetailResponse:
    import_ = composition.import_service.get_import(uow, import_id)
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
    uow: UowDep,
) -> Response:
    composition.import_service.delete_import(uow, import_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _to_summary(import_: Import) -> schemas.ImportSummaryResponse:
    return schemas.ImportSummaryResponse(
        import_id=import_.id,
        source_id=import_.source_account_id,
        source_name=import_.source_name,
        type=import_.type,
        ingestion_status=import_.ingestion_status,
        processing_status=import_.processing_status,
        created_at=import_.created_at,
        completed_at=import_.completed_at,
        file_count=import_.file_count,
        total_size=import_.total_size,
        import_hash=import_.import_hash,
    )


def _to_file(file_: ImportFile) -> schemas.FileResponse:
    return schemas.FileResponse(
        path=file_.path,
        sha256=file_.sha256,
        size=file_.size,
        format=file_.format,
        modified_at=file_.modified_at,
        storage_key=file_.storage_key,
    )
