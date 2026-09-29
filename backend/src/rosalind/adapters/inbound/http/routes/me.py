"""Current-account profile endpoint.

Returns the authenticated user's Rosalind account and IdP profile (a derived
projection of the persisted ``Account`` plus the token's identity claims).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from rosalind.adapters.inbound.http.dependencies import get_current_account_profile
from rosalind.adapters.inbound.http.schemas import me as schemas
from rosalind.application.read_models import CurrentAccount

router = APIRouter(tags=["me"])


@router.get("/me", response_model=schemas.AccountProfileResponse)
def me(
    profile: Annotated[CurrentAccount, Depends(get_current_account_profile)],
) -> schemas.AccountProfileResponse:
    return _to_response(profile)


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
