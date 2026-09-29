"""HTTP authentication dependency.

Turns a bearer token into the authenticated Rosalind ``Account``. Validation is
delegated to the injected ``TokenVerifier`` (Keycloak/JWKS); account/identity
resolution and just-in-time provisioning go through ``AccountService``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rosalind import config
from rosalind.adapters.composition import (
    get_account_service,
    get_token_verifier,
    get_uow,
)
from rosalind.application.errors import AccountNotFoundError
from rosalind.application.ports.identity import TokenVerifier
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.services.accounts import AccountService
from rosalind.domain.account import Account

bearer_scheme = HTTPBearer(auto_error=False)

UowDep = Annotated[UnitOfWork, Depends(get_uow)]
VerifierDep = Annotated[TokenVerifier, Depends(get_token_verifier)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]

_ANONYMOUS_ACCOUNT = Account(
    id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
    self_person_id=None,
    created_at=datetime.now(UTC),
    updated_at=datetime.now(UTC),
)


def get_current_account(
    credentials: CredentialsDep,
    uow: UowDep,
    verifier: VerifierDep,
    service: AccountServiceDep,
) -> Account:
    if not config.settings.auth_enabled:
        return _ANONYMOUS_ACCOUNT

    token = credentials.credentials if credentials is not None else None
    verified = verifier.verify(token) if token is not None else None
    if verified is None:
        raise _unauthorized()

    try:
        account = service.get_or_create(uow, verified.issuer, verified.subject)
    except AccountNotFoundError:
        raise _unauthorized() from None
    uow.commit()
    return account


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentAccountDep = Annotated[Account, Depends(get_current_account)]
