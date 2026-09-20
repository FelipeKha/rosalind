"""Provider-independent person observations.

These value objects record *what a source asserted* about a person, without any
Rosalind normalization, deduplication, or canonical primary selection. They are
transient: they are regenerated from ``raw.source_record`` whenever needed and
are never persisted directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRef:
    """An external identity within a specific source account.

    Not globally unique: the same ``(source_type, external_id)`` may refer to
    different people across different source accounts. The canonical identity is
    ``(source_account_id, source_type, external_id)`` in ``core.source_identity``.
    """

    source_type: str
    external_id: str


@dataclass(frozen=True)
class NameObservation:
    display_name: str | None
    given_name: str | None
    family_name: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class EmailObservation:
    value: str
    type: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class DateObservation:
    date_type: str
    year: int | None
    month: int | None
    day: int | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class GenderObservation:
    value: str
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class LocaleObservation:
    value: str
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class PersonObservation:
    source_identities: tuple[SourceRef, ...]
    names: tuple[NameObservation, ...]
    emails: tuple[EmailObservation, ...]
    dates: tuple[DateObservation, ...]
    genders: tuple[GenderObservation, ...]
    locales: tuple[LocaleObservation, ...]
