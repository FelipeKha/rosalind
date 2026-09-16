"""Import lifecycle endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from rosalind import config, models, object_storage
from rosalind.api.schemas import imports as schemas
from rosalind.db import get_db
from rosalind.ingestion import manifest, service
from rosalind.providers.google import people as google_people

router = APIRouter(prefix="/imports", tags=["imports"])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=schemas.ImportListResponse)
def list_imports(
    db: SessionDep,
) -> schemas.ImportListResponse:
    imports = service.list_imports(db)
    return schemas.ImportListResponse(
        imports=[_to_summary(import_) for import_ in imports]
    )


@router.post(
    "/google/takeout",
    response_model=schemas.ImportCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_google_takeout(
    db: SessionDep,
) -> schemas.ImportCreatedResponse:
    import_ = service.create_import(db, source="google", type_="takeout")
    return schemas.ImportCreatedResponse(
        import_id=import_.id,
        bucket=config.settings.s3_bucket,
        storage_prefix=manifest.storage_prefix(import_.id),
        status=import_.status,
    )


@router.post(
    "/google/profile",
    response_model=schemas.GoogleProfileImportResponse,
)
def import_google_profile(db: SessionDep) -> schemas.GoogleProfileImportResponse:
    result = google_people.import_profile(db)
    return schemas.GoogleProfileImportResponse(
        status=result.status,
        account=result.account,
        display_name=result.display_name,
        fetched_at=result.fetched_at,
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
    import_ = service.complete_import(db, import_id, entries)
    return _to_summary(import_)


@router.get(
    "/{import_id}",
    response_model=schemas.ImportDetailResponse,
)
def get_import(
    import_id: uuid.UUID,
    db: SessionDep,
) -> schemas.ImportDetailResponse:
    import_ = service.get_import(db, import_id)
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
    import_ = service.get_import(db, import_id)
    object_storage.delete_objects(
        config.settings.s3_bucket, [f.storage_key for f in import_.files]
    )
    service.delete_import(db, import_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _to_summary(import_: models.Import) -> schemas.ImportSummaryResponse:
    return schemas.ImportSummaryResponse(
        import_id=import_.id,
        source=import_.source,
        type=import_.type,
        status=import_.status,
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
