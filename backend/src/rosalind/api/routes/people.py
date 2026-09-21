"""Person read endpoints.

Handlers parse input -> call ``PersonService`` -> shape output. No SQL and no
business rules here; those live in ``PersonRepository`` and ``PersonService``.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from rosalind.api.schemas import people as schemas
from rosalind.db import get_db
from rosalind.repositories.person_repository import PersonRepository
from rosalind.services.person_service import PersonService

router = APIRouter(prefix="/people", tags=["people"])

SessionDep = Annotated[Session, Depends(get_db)]


def get_service() -> PersonService:
    return PersonService(PersonRepository())


ServiceDep = Annotated[PersonService, Depends(get_service)]


@router.get("/search", response_model=list[schemas.PersonProfileResponse])
def search_people(
    q: str,
    db: SessionDep,
    svc: ServiceDep,
) -> list[schemas.PersonProfileResponse]:
    return [
        schemas.PersonProfileResponse(**asdict(p)) for p in svc.search_people(db, q)
    ]


@router.get("/{person_id}", response_model=schemas.PersonProfileResponse)
def get_person(
    person_id: uuid.UUID,
    db: SessionDep,
    svc: ServiceDep,
) -> schemas.PersonProfileResponse:
    profile = svc.get_person(db, person_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"person {person_id} not found",
        )
    return schemas.PersonProfileResponse(**asdict(profile))
