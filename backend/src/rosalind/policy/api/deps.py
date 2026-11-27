"""FastAPI dependencies for the policy service."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from rosalind import config
from rosalind.adapters.outbound.keycloak.jwt import KeycloakJwtVerifier
from rosalind.adapters.outbound.persistence.session import SessionLocal
from rosalind.application.ports.identity import VerifiedToken
from rosalind.policy.adapters.llm_ollama import OllamaPromptParser
from rosalind.policy.adapters.persistence import PostgresPolicyRepository
from rosalind.policy.adapters.secret_box import FernetSecretBox
from rosalind.policy.application.interpreter import InterpreterService
from rosalind.policy.application.ports import AccountRef

bearer_scheme = HTTPBearer(auto_error=False)

_verifier = KeycloakJwtVerifier()
_ANONYMOUS = VerifiedToken(issuer="local", subject="anonymous")


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def get_repository(session: SessionDep) -> PostgresPolicyRepository:
    return PostgresPolicyRepository(session)


RepositoryDep = Annotated[PostgresPolicyRepository, Depends(get_repository)]


def get_verified_token(credentials: CredentialsDep) -> VerifiedToken:
    if not config.settings.auth_enabled:
        return _ANONYMOUS
    token = credentials.credentials if credentials is not None else None
    verified = _verifier.verify(token) if token is not None else None
    if verified is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verified


TokenDep = Annotated[VerifiedToken, Depends(get_verified_token)]


def get_current_account(token: TokenDep, repository: RepositoryDep) -> AccountRef:
    account = repository.get_or_create_account(token.issuer, token.subject)
    repository.commit()
    return account


AccountDep = Annotated[AccountRef, Depends(get_current_account)]


def get_service(repository: RepositoryDep) -> InterpreterService:
    settings = config.settings.policy
    return InterpreterService(
        repository=repository,
        parser_factory=lambda model: OllamaPromptParser(
            model, timeout=settings.request_timeout_seconds
        ),
        secret_box=FernetSecretBox(),
        settings=settings,
    )


ServiceDep = Annotated[InterpreterService, Depends(get_service)]
