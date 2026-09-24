"""Person read endpoints.

Handlers parse input -> call ``PersonService`` -> shape output. No SQL and no
business rules here; those live in ``PersonRepository`` and ``PersonService``.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from rosalind.adapters.inbound.http.schemas import people as schemas
from rosalind.adapters.outbound.persistence.session import get_person_service
from rosalind.application.services.people import PersonService

router = APIRouter(prefix="/people", tags=["people"])

ServiceDep = Annotated[PersonService, Depends(get_person_service)]


@router.get("", response_model=list[schemas.PersonProfileResponse])
def list_people(
    svc: ServiceDep,
) -> list[schemas.PersonProfileResponse]:
    return [schemas.PersonProfileResponse(**asdict(p)) for p in svc.list_people()]


@router.get("/search", response_model=list[schemas.PersonProfileResponse])
def search_people(
    q: str,
    svc: ServiceDep,
) -> list[schemas.PersonProfileResponse]:
    return [schemas.PersonProfileResponse(**asdict(p)) for p in svc.search_people(q)]


@router.get("/{person_id}", response_model=schemas.PersonProfileResponse)
def get_person(
    person_id: uuid.UUID,
    svc: ServiceDep,
) -> schemas.PersonProfileResponse:
    profile = svc.get_person(person_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"person {person_id} not found",
        )
    return schemas.PersonProfileResponse(**asdict(profile))
