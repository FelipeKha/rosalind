"""Provider-independent person observations.

These value objects record *what a source asserted* about a person, without any
Rosalind normalization, deduplication, or canonical primary selection. They are
transient: they are regenerated from ``raw.source_record`` whenever needed and
are never persisted directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from rosalind.domain.source import SourceRef


@dataclass(frozen=True)
class NameObservation:
    display_name: str | None
    given_name: str | None
    family_name: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str
    middle_name: str | None = None
    name_prefix: str | None = None
    name_suffix: str | None = None
    previous_family_name: str | None = None
    phonetic_given_name: str | None = None
    phonetic_middle_name: str | None = None
    phonetic_family_name: str | None = None
    phonetic_full_name: str | None = None


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
class PhoneObservation:
    value: str
    type: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class AddressObservation:
    formatted: str | None
    type: str | None
    street: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    country_code: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class OrganizationObservation:
    name: str | None
    department: str | None
    title: str | None
    type: str | None
    current: bool | None
    start_year: int | None
    start_month: int | None
    start_day: int | None
    end_year: int | None
    end_month: int | None
    end_day: int | None
    phonetic_name: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class UrlObservation:
    value: str
    type: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class ImObservation:
    service: str | None
    username: str
    type: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class NoteObservation:
    value: str
    content_type: str | None
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class RelationObservation:
    related_person_name: str | None
    type: str
    source: SourceRef | None
    source_primary: bool | None
    source_verified: bool | None
    field_path: str


@dataclass(frozen=True)
class NicknameObservation:
    value: str
    type: str | None
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
    phones: tuple[PhoneObservation, ...] = ()
    addresses: tuple[AddressObservation, ...] = ()
    organizations: tuple[OrganizationObservation, ...] = ()
    urls: tuple[UrlObservation, ...] = ()
    ims: tuple[ImObservation, ...] = ()
    notes: tuple[NoteObservation, ...] = ()
    relations: tuple[RelationObservation, ...] = ()
    nicknames: tuple[NicknameObservation, ...] = ()
