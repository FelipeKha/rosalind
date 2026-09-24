"""Person read endpoints.

Handlers parse input -> call ``PersonService`` -> shape output. No SQL and no
business rules here; those live in ``PersonRepository`` and ``PersonService``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from rosalind.adapters.composition import get_person_service
from rosalind.adapters.inbound.http.schemas import people as schemas
from rosalind.application.read_models import PersonProfile
from rosalind.application.services.people import PersonService

router = APIRouter(prefix="/people", tags=["people"])

ServiceDep = Annotated[PersonService, Depends(get_person_service)]


@router.get("", response_model=list[schemas.PersonProfileResponse])
def list_people(
    svc: ServiceDep,
) -> list[schemas.PersonProfileResponse]:
    return [_to_response(p) for p in svc.list_people()]


@router.get("/search", response_model=list[schemas.PersonProfileResponse])
def search_people(
    q: str,
    svc: ServiceDep,
) -> list[schemas.PersonProfileResponse]:
    return [_to_response(p) for p in svc.search_people(q)]


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
    return _to_response(profile)


def _to_response(profile: PersonProfile) -> schemas.PersonProfileResponse:
    return schemas.PersonProfileResponse(
        person_id=profile.person_id,
        display_name=profile.display_name,
        given_name=profile.given_name,
        family_name=profile.family_name,
        primary_email=profile.primary_email,
        email_verified=profile.email_verified,
        gender=profile.gender,
        locale=profile.locale,
        birth_year=profile.birth_year,
        birth_month=profile.birth_month,
        birth_day=profile.birth_day,
    )
