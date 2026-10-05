"""Current-account profile endpoint.

Returns the authenticated user's Rosalind account and IdP profile (a derived
projection of the persisted ``Account`` plus the token's identity claims), and
allows the account owner to explicitly link their self person.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from rosalind.adapters.composition import get_account_service, get_uow
from rosalind.adapters.inbound.http.dependencies import (
    AccountDep,
    get_current_account_profile,
)
from rosalind.adapters.inbound.http.schemas import me as schemas
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.read_models import CurrentAccount
from rosalind.application.services.accounts import AccountService

router = APIRouter(tags=["me"])

UowDep = Annotated[UnitOfWork, Depends(get_uow)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


@router.get("/me", response_model=schemas.AccountProfileResponse)
def me(
    profile: Annotated[CurrentAccount, Depends(get_current_account_profile)],
) -> schemas.AccountProfileResponse:
    return _to_response(profile)


@router.put("/me/self-person", response_model=schemas.SetSelfPersonResponse)
def set_self_person(
    body: schemas.SetSelfPersonRequest,
    uow: UowDep,
    account: AccountDep,
    service: AccountServiceDep,
) -> schemas.SetSelfPersonResponse:
    service.set_self_person(uow, account.id, body.person_id)
    return schemas.SetSelfPersonResponse(self_person_id=body.person_id)


def _to_response(profile: CurrentAccount) -> schemas.AccountProfileResponse:
    return schemas.AccountProfileResponse(
        account_id=profile.account_id,
        self_person_id=profile.self_person_id,
        created_at=profile.created_at,
        subject=profile.subject,
        email=profile.email,
        preferred_username=profile.preferred_username,
        given_name=profile.given_name,
        family_name=profile.family_name,
    )
