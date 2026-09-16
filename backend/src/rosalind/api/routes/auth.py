"""Google OAuth authorization endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from rosalind.api.schemas import auth as schemas
from rosalind.auth import service
from rosalind.db import get_db

router = APIRouter(prefix="/auth/google", tags=["auth"])

SessionDep = Annotated[Session, Depends(get_db)]


@router.post("/connect", response_model=schemas.ConnectResponse)
def connect(db: SessionDep) -> schemas.ConnectResponse:
    result = service.start_connect(db, "google")
    return schemas.ConnectResponse(auth_url=result.auth_url, state=result.state)


@router.get("/callback", response_class=HTMLResponse)
def callback(state: str, code: str, db: SessionDep) -> HTMLResponse:
    service.complete_connect(db, state, code)
    return HTMLResponse(
        "<h1>Rosalind</h1><p>Google account connected. You can close this tab.</p>"
    )


@router.get("/status", response_model=schemas.AuthStatusResponse)
def status(state: str, db: SessionDep) -> schemas.AuthStatusResponse:
    result = service.get_status(db, state)
    return schemas.AuthStatusResponse(
        status=result.status,
        source_account_id=result.source_account_id,
        display_name=result.display_name,
    )
