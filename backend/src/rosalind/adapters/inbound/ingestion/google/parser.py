"""Deterministic mapper from Google ``Person`` to source observations.

The mapper is a pure function: no database access, no normalization, no fuzzy
matching. It must produce the same ``PersonObservation`` for the same input.
"""

from __future__ import annotations

from typing import Any

from rosalind.adapters.inbound.ingestion.google.models import (
    GOOGLE_PERSON_RESOURCE_TYPE,
    GoogleAddress,
    GoogleBiography,
    GoogleBirthday,
    GoogleDate,
    GoogleEmailAddress,
    GoogleFieldMetadata,
    GoogleGender,
    GoogleImClient,
    GoogleLocale,
    GoogleName,
    GoogleNickname,
    GoogleOrganization,
    GooglePerson,
    GooglePhoneNumber,
    GoogleRelation,
    GoogleSource,
    GoogleUrl,
)
from rosalind.application.errors import InvalidPayloadError
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
    PersonObservation,
    PhoneObservation,
    RelationObservation,
    UrlObservation,
)
from rosalind.domain.source import SourceRef


def _date_parts(date: GoogleDate | None) -> tuple[int | None, int | None, int | None]:
    if date is None:
        return None, None, None
    return date.year or None, date.month or None, date.day or None


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
    phones = tuple(
        _map_phone(phone, index) for index, phone in enumerate(person.phoneNumbers)
    )
    addresses = tuple(
        _map_address(address, index) for index, address in enumerate(person.addresses)
    )
    organizations = tuple(
        _map_organization(org, index) for index, org in enumerate(person.organizations)
    )
    urls = tuple(_map_url(url, index) for index, url in enumerate(person.urls))
    ims = tuple(_map_im(client, index) for index, client in enumerate(person.imClients))
    notes = tuple(_map_note(bio, index) for index, bio in enumerate(person.biographies))
    relations = tuple(
        _map_relation(relation, index)
        for index, relation in enumerate(person.relations)
        if relation.type and relation.person
    )
    nicknames = tuple(
        _map_nickname(nickname, index)
        for index, nickname in enumerate(person.nicknames)
        if nickname.value
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
        phones=phones,
        addresses=addresses,
        organizations=organizations,
        urls=urls,
        ims=ims,
        notes=notes,
        relations=relations,
        nicknames=nicknames,
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
    for phone in person.phoneNumbers:
        _add_field_source(refs, phone.metadata)
    for address in person.addresses:
        _add_field_source(refs, address.metadata)
    for org in person.organizations:
        _add_field_source(refs, org.metadata)
    for url in person.urls:
        _add_field_source(refs, url.metadata)
    for client in person.imClients:
        _add_field_source(refs, client.metadata)
    for bio in person.biographies:
        _add_field_source(refs, bio.metadata)
    for relation in person.relations:
        _add_field_source(refs, relation.metadata)
    for nickname in person.nicknames:
        _add_field_source(refs, nickname.metadata)
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
        middle_name=name.middleName,
        name_prefix=name.honorificPrefix,
        name_suffix=name.honorificSuffix,
        phonetic_given_name=name.phoneticGivenName,
        phonetic_middle_name=name.phoneticMiddleName,
        phonetic_family_name=name.phoneticFamilyName,
        phonetic_full_name=name.phoneticFullName,
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


def _map_phone(phone: GooglePhoneNumber, index: int) -> PhoneObservation:
    primary, verified = _flags(phone.metadata)
    return PhoneObservation(
        value=phone.value,
        type=phone.type,
        source=_field_source(phone.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.phoneNumbers[{index}]",
    )


def _map_address(address: GoogleAddress, index: int) -> AddressObservation:
    primary, verified = _flags(address.metadata)
    return AddressObservation(
        formatted=address.formattedValue,
        type=address.type,
        street=address.streetAddress,
        city=address.city,
        region=address.region,
        postal_code=address.postalCode,
        country=address.country,
        country_code=address.countryCode,
        source=_field_source(address.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.addresses[{index}]",
    )


def _map_organization(org: GoogleOrganization, index: int) -> OrganizationObservation:
    primary, verified = _flags(org.metadata)
    start_year, start_month, start_day = _date_parts(org.startDate)
    end_year, end_month, end_day = _date_parts(org.endDate)
    return OrganizationObservation(
        name=org.name,
        department=org.department,
        title=org.title,
        type=org.type,
        current=org.current,
        start_year=start_year,
        start_month=start_month,
        start_day=start_day,
        end_year=end_year,
        end_month=end_month,
        end_day=end_day,
        phonetic_name=org.phoneticName,
        source=_field_source(org.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.organizations[{index}]",
    )


def _map_url(url: GoogleUrl, index: int) -> UrlObservation:
    primary, verified = _flags(url.metadata)
    return UrlObservation(
        value=url.value,
        type=url.type,
        source=_field_source(url.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.urls[{index}]",
    )


def _map_im(client: GoogleImClient, index: int) -> ImObservation:
    primary, verified = _flags(client.metadata)
    return ImObservation(
        service=client.protocol,
        username=client.username,
        type=client.type,
        source=_field_source(client.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.imClients[{index}]",
    )


def _map_note(bio: GoogleBiography, index: int) -> NoteObservation:
    primary, verified = _flags(bio.metadata)
    return NoteObservation(
        value=bio.value,
        content_type=bio.contentType,
        source=_field_source(bio.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.biographies[{index}]",
    )


def _map_relation(relation: GoogleRelation, index: int) -> RelationObservation:
    primary, verified = _flags(relation.metadata)
    return RelationObservation(
        related_person_name=relation.person,
        type=relation.type or "",
        source=_field_source(relation.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.relations[{index}]",
    )


def _map_nickname(nickname: GoogleNickname, index: int) -> NicknameObservation:
    primary, verified = _flags(nickname.metadata)
    return NicknameObservation(
        value=nickname.value,
        type=nickname.type,
        source=_field_source(nickname.metadata),
        source_primary=primary,
        source_verified=verified,
        field_path=f"$.nicknames[{index}]",
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


class GooglePersonParser:
    """``PersonParser`` implementation for the Google People ``Person`` resource.

    Provider-specific concerns (resource identity, etag, validation) stay here;
    the resulting ``PersonObservation`` is provider-independent.
    """

    resource_type = GOOGLE_PERSON_RESOURCE_TYPE

    def external_id(self, payload: dict[str, Any]) -> str:
        resource_name = payload.get("resourceName")
        if not resource_name:
            raise InvalidPayloadError("provider payload is missing resourceName")
        return resource_name if isinstance(resource_name, str) else str(resource_name)

    def source_etag(self, payload: dict[str, Any]) -> str | None:
        return payload.get("etag")

    def parse(self, payload: dict[str, Any]) -> PersonObservation:
        return map_google_person(GooglePerson.model_validate(payload))
