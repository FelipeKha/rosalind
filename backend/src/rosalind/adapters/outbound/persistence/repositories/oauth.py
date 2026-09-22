"""Persistence for OAuth credentials and authorization requests.

This is where at-rest encryption/decryption lives: the application layer reads
and writes plaintext ``StoredCredential`` value objects, and these repositories
translate to/from the encrypted ORM columns. Mutations flush but do not commit
so they can join a larger service-level transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rosalind import security
from rosalind.adapters.outbound.persistence.models.source import (
    OAuthAuthRequest as OAuthAuthRequestModel,
)
from rosalind.adapters.outbound.persistence.models.source import (
    OAuthCredential as OAuthCredentialModel,
)
from rosalind.application.ports.repositories import AuthRequest, StoredCredential

_TOKEN_TYPE = "Bearer"  # nosec B105


class PostgresOAuthCredentialRepository:
    def exists(self, db: Session, source_account_id: uuid.UUID) -> bool:
        return (
            db.scalar(
                select(OAuthCredentialModel.id).where(
                    OAuthCredentialModel.source_account_id == source_account_id
                )
            )
            is not None
        )

    def get_latest(
        self, db: Session, source_account_id: uuid.UUID
    ) -> StoredCredential | None:
        model = db.scalars(
            select(OAuthCredentialModel)
            .where(OAuthCredentialModel.source_account_id == source_account_id)
            .order_by(OAuthCredentialModel.created_at.desc())
        ).first()
        if model is None:
            return None
        return self._to_domain(model, tolerate_decrypt_failure=False)

    def list_all(
        self, db: Session, source_account_id: uuid.UUID
    ) -> list[StoredCredential]:
        models = db.scalars(
            select(OAuthCredentialModel).where(
                OAuthCredentialModel.source_account_id == source_account_id
            )
        ).all()
        return [
            self._to_domain(model, tolerate_decrypt_failure=True) for model in models
        ]

    def upsert(
        self,
        db: Session,
        *,
        account_id: uuid.UUID,
        provider: str,
        access_token: str,
        refresh_token: str | None,
        scopes: list[str] | None,
        expires_at: datetime | None,
    ) -> None:
        credential = db.scalars(
            select(OAuthCredentialModel).where(
                OAuthCredentialModel.source_account_id == account_id,
                OAuthCredentialModel.provider == provider,
            )
        ).first()
        if credential is None:
            credential = OAuthCredentialModel(
                provider=provider, source_account_id=account_id
            )
            db.add(credential)

        credential.token_type = _TOKEN_TYPE
        credential.access_token_encrypted = security.encrypt_secret(access_token)
        credential.refresh_token_encrypted = (
            security.encrypt_secret(refresh_token) if refresh_token else None
        )
        credential.scope = " ".join(scopes) if scopes else None
        credential.expires_at = expires_at

    def update_tokens(
        self,
        db: Session,
        *,
        account_id: uuid.UUID,
        provider: str,
        access_token: str,
        expires_at: datetime | None,
    ) -> None:
        credential = db.scalars(
            select(OAuthCredentialModel).where(
                OAuthCredentialModel.source_account_id == account_id,
                OAuthCredentialModel.provider == provider,
            )
        ).first()
        if credential is None:
            return
        credential.access_token_encrypted = security.encrypt_secret(access_token)
        credential.expires_at = expires_at

    def delete_all(self, db: Session, source_account_id: uuid.UUID) -> None:
        models = db.scalars(
            select(OAuthCredentialModel).where(
                OAuthCredentialModel.source_account_id == source_account_id
            )
        ).all()
        for model in models:
            db.delete(model)

    @staticmethod
    def _to_domain(
        model: OAuthCredentialModel, *, tolerate_decrypt_failure: bool
    ) -> StoredCredential:
        access_token: str | None = None
        refresh_token: str | None = None
        try:
            access_token = security.decrypt_secret(model.access_token_encrypted)
        except security.SecurityError:
            if not tolerate_decrypt_failure:
                raise
        if model.refresh_token_encrypted is not None:
            try:
                refresh_token = security.decrypt_secret(model.refresh_token_encrypted)
            except security.SecurityError:
                if not tolerate_decrypt_failure:
                    raise
        return StoredCredential(
            provider=model.provider,
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=model.scope.split() if model.scope else None,
            expires_at=model.expires_at,
        )


class PostgresOAuthAuthRequestRepository:
    def create(
        self,
        db: Session,
        *,
        state: str,
        source_account_id: uuid.UUID,
        source_name: str | None,
        code_verifier: str | None,
        expires_at: datetime,
    ) -> None:
        db.add(
            OAuthAuthRequestModel(
                state=state,
                source_account_id=source_account_id,
                source_name=source_name,
                code_verifier=code_verifier,
                expires_at=expires_at,
            )
        )

    def get(self, db: Session, state: str) -> AuthRequest | None:
        model = db.get(OAuthAuthRequestModel, state)
        if model is None:
            return None
        return AuthRequest(
            state=model.state,
            source_account_id=model.source_account_id,
            source_name=model.source_name,
            status=model.status,
            code_verifier=model.code_verifier,
            expires_at=model.expires_at,
            consumed_at=model.consumed_at,
        )

    def reassign(self, db: Session, state: str, source_account_id: uuid.UUID) -> None:
        model = db.get(OAuthAuthRequestModel, state)
        if model is None:
            return
        model.source_account_id = source_account_id
        db.flush()

    def mark_connected(self, db: Session, state: str, consumed_at: datetime) -> None:
        model = db.get(OAuthAuthRequestModel, state)
        if model is None:
            return
        model.status = "connected"
        model.consumed_at = consumed_at
