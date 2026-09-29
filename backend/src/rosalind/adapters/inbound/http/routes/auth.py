"""Provider OAuth callback endpoint.

The callback path is provider-bound (fixed in the Google OAuth console), so it
stays here even though the connect/status/disconnect surface lives under
``/sources``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from rosalind.adapters.composition import get_source_service, get_uow
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.services.sources import SourceService

router = APIRouter(prefix="/auth/google", tags=["auth"])

UowDep = Annotated[UnitOfWork, Depends(get_uow)]
SourceDep = Annotated[SourceService, Depends(get_source_service)]


@router.get("/callback", response_class=HTMLResponse)
def callback(state: str, code: str, uow: UowDep, service: SourceDep) -> HTMLResponse:
    service.complete_connect(uow, state, code)
    return HTMLResponse(
        "<h1>Rosalind</h1><p>Google account connected. You can close this tab.</p>"
    )
