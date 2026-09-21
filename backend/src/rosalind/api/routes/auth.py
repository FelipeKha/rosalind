"""Provider OAuth callback endpoint.

The callback path is provider-bound (fixed in the Google OAuth console), so it
stays here even though the connect/status/disconnect surface lives under
``/sources``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from rosalind.db import get_db
from rosalind.services import sources as service

router = APIRouter(prefix="/auth/google", tags=["auth"])

SessionDep = Annotated[Session, Depends(get_db)]


@router.get("/callback", response_class=HTMLResponse)
def callback(state: str, code: str, db: SessionDep) -> HTMLResponse:
    service.complete_connect(db, state, code)
    return HTMLResponse(
        "<h1>Rosalind</h1><p>Google account connected. You can close this tab.</p>"
    )
