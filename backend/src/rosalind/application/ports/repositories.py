"""Persistence ports (interfaces) for repositories.

The concrete implementations live in ``adapters.outbound.persistence`` and
satisfy these protocols structurally. Repositories are session-bound: they are
constructed with a database session by the persistence adapter and expose
session-free methods to the application layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from rosalind.application.read_models import PersonProfile
from rosalind.domain.account import Account, AccountIdentity
from rosalind.domain.person import (
    AddressObservation,
    DateObservation,
    EmailObservation,
    GenderObservation,
    ImObservation,
    LocaleObservation,
    NameObservation,
    NicknameObservation,
    NoteObservation,
    OrganizationObservation,
    PhoneObservation,
    RelationObservation,
    UrlObservation,
)
from rosalind.domain.source import (
    Import,
    ImportFile,
    SourceAccount,
    SourceRecord,
    SourceRef,
)


@dataclass(frozen=True)
class FactUpsertResult:
    """Outcome of recording one observation as a canonical fact.

    Reports whether the canonical fact and its supporting assertion were newly
    created, so the caller can tally idempotency counters without knowing how
    many rows (fact, assertion, link) the adapter touched.
    """

    fact_id: uuid.UUID
    fact_created: bool
    assertion_created: bool


@dataclass(frozen=True)
class UnresolvedRelation:
    """A relation edge whose target person has not been resolved yet."""

    relation_id: uuid.UUID
    person_id: uuid.UUID
    related_person_name: str


@dataclass(frozen=True)
class StoredCredential:
    """Plaintext OAuth credential bundle as read from persistence.

    Tokens are decrypted by the adapter, so the application layer never touches
    encryption. ``access_token``/``refresh_token`` may be ``None`` when a stored
    token could not be decrypted (e.g. for best-effort revocation).
    """

    provider: str
    access_token: str | None
    refresh_token: str | None
    scopes: list[str] | None
    expires_at: datetime | None


@dataclass(frozen=True)
class AuthRequest:
    """A pending (or completed) OAuth authorization request."""

    state: str
    source_account_id: uuid.UUID
    source_name: str | None
    status: str
    code_verifier: str | None
    expires_at: datetime
    consumed_at: datetime | None


class PersonRepository(Protocol):
    def search(
        self, account_id: uuid.UUID, query: str, limit: int
    ) -> list[PersonProfile]: ...

    def list_all(self, account_id: uuid.UUID, limit: int) -> list[PersonProfile]: ...

    def get(
        self, account_id: uuid.UUID, person_id: uuid.UUID
    ) -> PersonProfile | None: ...


class AccountIdentityRepository(Protocol):
    def get(self, issuer: str, subject: str) -> AccountIdentity | None: ...

    def get_or_create(self, issuer: str, subject: str) -> AccountIdentity: ...

    def touch(self, identity_id: uuid.UUID, last_seen_at: datetime) -> None: ...


class AccountRepository(Protocol):
    def get(self, account_id: uuid.UUID) -> Account | None: ...


class SourceRecordRepository(Protocol):
    def persist(
        self,
        *,
        source_account: SourceAccount,
        resource_type: str,
        external_id: str,
        payload: dict[str, Any],
        payload_sha256: str,
        source_etag: str | None = None,
        source_updated_at: datetime | None = None,
        import_id: uuid.UUID | None = None,
    ) -> SourceRecord: ...

    def list_for_import(self, import_id: uuid.UUID) -> list[SourceRecord]: ...


class SourceAccountRepository(Protocol):
    def get(self, source_id: uuid.UUID) -> SourceAccount | None: ...

    def get_by_name(self, account_id: uuid.UUID, name: str) -> SourceAccount | None: ...

    def get_by_identity(
        self, account_id: uuid.UUID, provider: str, account_identifier: str
    ) -> SourceAccount | None: ...

    def list(self, account_id: uuid.UUID) -> list[SourceAccount]: ...

    def create(
        self, *, account_id: uuid.UUID, provider: str, name: str | None = None
    ) -> SourceAccount: ...

    def update(self, account: SourceAccount) -> SourceAccount: ...

    def delete(self, source_id: uuid.UUID) -> None: ...

    def store_sync_state(
        self, *, source_id: uuid.UUID, provider: str, sync_state: dict
    ) -> None: ...


class OAuthCredentialRepository(Protocol):
    def exists(self, source_account_id: uuid.UUID) -> bool: ...

    def get_latest(self, source_account_id: uuid.UUID) -> StoredCredential | None: ...

    def list_all(self, source_account_id: uuid.UUID) -> list[StoredCredential]: ...

    def upsert(
        self,
        *,
        account_id: uuid.UUID,
        provider: str,
        access_token: str,
        refresh_token: str | None,
        scopes: list[str] | None,
        expires_at: datetime | None,
    ) -> None: ...

    def update_tokens(
        self,
        *,
        account_id: uuid.UUID,
        provider: str,
        access_token: str,
        expires_at: datetime | None,
    ) -> None: ...

    def delete_all(self, source_account_id: uuid.UUID) -> None: ...


class OAuthAuthRequestRepository(Protocol):
    def create(
        self,
        *,
        state: str,
        source_account_id: uuid.UUID,
        source_name: str | None,
        code_verifier: str | None,
        expires_at: datetime,
    ) -> None: ...

    def get(self, state: str) -> AuthRequest | None: ...

    def reassign(self, state: str, source_account_id: uuid.UUID) -> None: ...

    def mark_connected(self, state: str, consumed_at: datetime) -> None: ...


class ImportRepository(Protocol):
    def create(
        self, *, account_id: uuid.UUID, source_account_id: uuid.UUID, type_: str
    ) -> Import: ...

    def get(self, import_id: uuid.UUID) -> Import | None: ...

    def list(self, account_id: uuid.UUID) -> list[Import]: ...

    def complete(
        self,
        import_id: uuid.UUID,
        *,
        files: Sequence[ImportFile],
        file_count: int,
        total_size: int,
        import_hash: str,
        completed_at: datetime,
    ) -> Import: ...

    def set_processing_status(self, import_id: uuid.UUID, status: str) -> Import: ...

    def mark_completed(
        self, import_id: uuid.UUID, *, completed_at: datetime
    ) -> Import: ...

    def delete(self, import_id: uuid.UUID) -> None: ...


class PersonCanonicalRepository(Protocol):
    """Write port for canonicalizing person observations.

    Operates only on domain value objects; the adapter owns the SQL and the
    concrete fact/assertion/link tables behind each operation.
    """

    def find_person_ids(
        self, *, source_account_id: uuid.UUID, refs: tuple[SourceRef, ...]
    ) -> set[uuid.UUID]: ...

    def create_person(self) -> uuid.UUID: ...

    def upsert_source_identity(
        self,
        *,
        source_account_id: uuid.UUID,
        person_id: uuid.UUID,
        refs: tuple[SourceRef, ...],
        resource_name: str,
    ) -> dict[SourceRef, uuid.UUID]: ...

    def upsert_name(
        self,
        *,
        person_id: uuid.UUID,
        observation: NameObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_email(
        self,
        *,
        person_id: uuid.UUID,
        observation: EmailObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_date(
        self,
        *,
        person_id: uuid.UUID,
        observation: DateObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_gender(
        self,
        *,
        person_id: uuid.UUID,
        observation: GenderObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_locale(
        self,
        *,
        person_id: uuid.UUID,
        observation: LocaleObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_phone(
        self,
        *,
        person_id: uuid.UUID,
        observation: PhoneObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_address(
        self,
        *,
        person_id: uuid.UUID,
        observation: AddressObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_organization(
        self,
        *,
        person_id: uuid.UUID,
        observation: OrganizationObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_url(
        self,
        *,
        person_id: uuid.UUID,
        observation: UrlObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_im(
        self,
        *,
        person_id: uuid.UUID,
        observation: ImObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_note(
        self,
        *,
        person_id: uuid.UUID,
        observation: NoteObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_relation(
        self,
        *,
        person_id: uuid.UUID,
        observation: RelationObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def upsert_nickname(
        self,
        *,
        person_id: uuid.UUID,
        observation: NicknameObservation,
        source_record_id: uuid.UUID,
        source_identity_id: uuid.UUID | None,
    ) -> FactUpsertResult: ...

    def set_name_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_email_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_date_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_gender_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_locale_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_phone_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_address_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_organization_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_url_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_im_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_note_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def set_nickname_primary(
        self, *, person_id: uuid.UUID, fact_id: uuid.UUID | None
    ) -> None: ...

    def list_unresolved_relations(self) -> list[UnresolvedRelation]: ...

    def find_person_ids_by_name(self, *, normalized_name: str) -> set[uuid.UUID]: ...

    def link_relation(
        self, *, relation_id: uuid.UUID, related_person_id: uuid.UUID
    ) -> None: ...
