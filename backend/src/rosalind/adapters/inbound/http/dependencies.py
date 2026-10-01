"""HTTP authentication dependency.

Turns a bearer token into the authenticated Rosalind ``Account``. Validation is
delegated to the injected ``TokenVerifier`` (Keycloak/JWKS); account/identity
resolution and just-in-time provisioning go through ``AccountService``.
"""

from __future__ import annotations

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
from rosalind.application.ports.identity import TokenVerifier, VerifiedToken
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.application.read_models import CurrentAccount, current_account_from
from rosalind.application.services.accounts import AccountService
from rosalind.domain.account import Account

bearer_scheme = HTTPBearer(auto_error=False)

UowDep = Annotated[UnitOfWork, Depends(get_uow)]
VerifierDep = Annotated[TokenVerifier, Depends(get_token_verifier)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]

_ANONYMOUS_TOKEN = VerifiedToken(issuer="local", subject="anonymous")


def get_verified_token(
    credentials: CredentialsDep,
    verifier: VerifierDep,
) -> VerifiedToken:
    if not config.settings.auth_enabled:
        return _ANONYMOUS_TOKEN

    token = credentials.credentials if credentials is not None else None
    verified = verifier.verify(token) if token is not None else None
    if verified is None:
        raise _unauthorized()
    return verified


def get_current_account(
    token: Annotated[VerifiedToken, Depends(get_verified_token)],
    uow: UowDep,
    service: AccountServiceDep,
) -> Account:
    try:
        account = service.get_or_create(uow, token.issuer, token.subject)
    except AccountNotFoundError:
        raise _unauthorized() from None
    uow.commit()
    return account


AccountDep = Annotated[Account, Depends(get_current_account)]


def get_current_account_profile(
    account: Annotated[Account, Depends(get_current_account)],
    token: Annotated[VerifiedToken, Depends(get_verified_token)],
) -> CurrentAccount:
    return current_account_from(
        account,
        subject=token.subject,
        email=token.email,
        preferred_username=token.preferred_username,
        given_name=token.given_name,
        family_name=token.family_name,
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
