"""Deterministic mapper from Google ``Person`` to source observations.

The mapper is a pure function: no database access, no normalization, no fuzzy
matching. It must produce the same ``PersonObservation`` for the same input.
"""

from __future__ import annotations

from rosalind.domain.observations.person import (
    DateObservation,
    EmailObservation,
    GenderObservation,
    LocaleObservation,
    NameObservation,
    PersonObservation,
    SourceRef,
)
from rosalind.ingestion.google.models import (
    GoogleBirthday,
    GoogleEmailAddress,
    GoogleFieldMetadata,
    GoogleGender,
    GoogleLocale,
    GoogleName,
    GooglePerson,
    GoogleSource,
)


def map_google_person(person: GooglePerson) -> PersonObservation:
    """Map a validated ``GooglePerson`` into a provider-independent observation."""
    identities = _collect_source_identities(person)

    names = tuple(
        _map_name(name, index)
        for index, name in enumerate(person.names)
        if name.displayName or name.givenName or name.familyName
    )
    emails = tuple(
        _map_email(email, index) for index, email in enumerate(person.emailAddresses)
    )
    dates = tuple(
        _map_birthday(birthday, index)
        for index, birthday in enumerate(person.birthdays)
    )
    genders = tuple(
        _map_gender(gender, index)
        for index, gender in enumerate(person.genders)
        if gender.value
    )
    locales = tuple(
        _map_locale(locale, index)
        for index, locale in enumerate(person.locales)
        if locale.value
    )

    return PersonObservation(
        source_identities=tuple(identities.values()),
        names=names,
        emails=emails,
        dates=dates,
        genders=genders,
        locales=locales,
    )


def _collect_source_identities(
    person: GooglePerson,
) -> dict[tuple[str, str], SourceRef]:
    """Union of person-level and field-level source references, keyed by (type, id)."""
    refs: dict[tuple[str, str], SourceRef] = {}

    if person.metadata is not None:
        for source in person.metadata.sources:
            _add_source_ref(refs, source)

    for name in person.names:
        _add_field_source(refs, name.metadata)
    for email in person.emailAddresses:
        _add_field_source(refs, email.metadata)
    for birthday in person.birthdays:
        _add_field_source(refs, birthday.metadata)
    for gender in person.genders:
        _add_field_source(refs, gender.metadata)
    for locale in person.locales:
        _add_field_source(refs, locale.metadata)

    return refs


def _add_field_source(
    refs: dict[tuple[str, str], SourceRef], metadata: GoogleFieldMetadata | None
) -> None:
    if metadata is not None and metadata.source is not None:
        _add_source_ref(refs, metadata.source)


def _add_source_ref(
    refs: dict[tuple[str, str], SourceRef], source: GoogleSource | None
) -> None:
    ref = _source_ref(source)
    if ref is not None:
        refs[(ref.source_type, ref.external_id)] = ref


def _source_ref(source: GoogleSource | None) -> SourceRef | None:
    if source is None or not source.id:
        return None
    return SourceRef(source_type=source.type, external_id=source.id)


def _flags(metadata: GoogleFieldMetadata | None) -> tuple[bool | None, bool | None]:
    if metadata is None:
        return None, None
    return metadata.primary, metadata.verified


def _field_source(metadata: GoogleFieldMetadata | None) -> SourceRef | None:
    if metadata is None or metadata.source is None:
        return None
    return _source_ref(metadata.source)


def _map_name(name: GoogleName, index: int) -> NameObservation:
    primary, verified = _flags(name.metadata)
    return NameObservation(
        display_name=name.displayName,
        given_name=name.givenName,
        family_name=name.familyName,
        source=_field_source(name.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.names[{index}]",
    )


def _map_email(email: GoogleEmailAddress, index: int) -> EmailObservation:
    primary, verified = _flags(email.metadata)
    return EmailObservation(
        value=email.value,
        type=email.type,
        source=_field_source(email.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.emailAddresses[{index}]",
    )


def _map_birthday(birthday: GoogleBirthday, index: int) -> DateObservation:
    primary, verified = _flags(birthday.metadata)
    return DateObservation(
        date_type="birthday",
        year=birthday.date.year or None,
        month=birthday.date.month or None,
        day=birthday.date.day or None,
        source=_field_source(birthday.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.birthdays[{index}]",
    )


def _map_gender(gender: GoogleGender, index: int) -> GenderObservation:
    primary, verified = _flags(gender.metadata)
    return GenderObservation(
        value=gender.value or "",
        source=_field_source(gender.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.genders[{index}]",
    )


def _map_locale(locale: GoogleLocale, index: int) -> LocaleObservation:
    primary, verified = _flags(locale.metadata)
    return LocaleObservation(
        value=locale.value,
        source=_field_source(locale.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.locales[{index}]",
    )
