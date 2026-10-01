"""Pydantic models mirroring the Google People API ``Person`` resource.

These are intentionally close to Google's representation rather than Rosalind's
canonical model. Only the fields Rosalind currently consumes are typed; every
other field is preserved via ``extra="allow"`` and, more importantly, the
complete payload is retained in ``raw.source_record``.

https://developers.google.com/people/api/rest/v1/people#Person
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

GOOGLE_PERSON_RESOURCE_TYPE = "people.person"


class GoogleSource(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    id: str
    etag: str | None = None
    updateTime: datetime | None = None


class GoogleFieldMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    primary: bool | None = None
    verified: bool | None = None
    source: GoogleSource | None = None
    sourcePrimary: bool | None = None


class GoogleName(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    displayName: str | None = None
    givenName: str | None = None
    familyName: str | None = None
    middleName: str | None = None
    honorificPrefix: str | None = None
    honorificSuffix: str | None = None
    displayNameLastFirst: str | None = None
    unstructuredName: str | None = None
    phoneticFullName: str | None = None
    phoneticFamilyName: str | None = None
    phoneticGivenName: str | None = None
    phoneticMiddleName: str | None = None


class GoogleEmailAddress(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    value: str
    type: str | None = None
    formattedType: str | None = None


class GoogleDate(BaseModel):
    model_config = ConfigDict(extra="allow")

    year: int = 0
    month: int = 0
    day: int = 0


class GoogleBirthday(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    date: GoogleDate


class GoogleGender(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    value: str | None = None
    formattedValue: str | None = None


class GoogleLocale(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    value: str


class GooglePhoneNumber(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    value: str
    canonicalForm: str | None = None
    type: str | None = None


class GoogleAddress(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    formattedValue: str | None = None
    type: str | None = None
    streetAddress: str | None = None
    city: str | None = None
    region: str | None = None
    postalCode: str | None = None
    country: str | None = None
    countryCode: str | None = None


class GoogleOrganization(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    name: str | None = None
    department: str | None = None
    title: str | None = None
    type: str | None = None
    current: bool | None = None
    startDate: GoogleDate | None = None
    endDate: GoogleDate | None = None
    phoneticName: str | None = None


class GoogleUrl(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    value: str
    type: str | None = None


class GoogleImClient(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    username: str
    type: str | None = None
    protocol: str | None = None


class GoogleBiography(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    value: str
    contentType: str | None = None


class GoogleRelation(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    person: str | None = None
    type: str | None = None


class GoogleNickname(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: GoogleFieldMetadata | None = None
    value: str
    type: str | None = None


class GooglePersonMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    sources: list[GoogleSource] = Field(default_factory=list)
    objectType: str | None = None
    deleted: bool | None = None


class GooglePerson(BaseModel):
    model_config = ConfigDict(extra="allow")

    resourceName: str
    etag: str | None = None
    metadata: GooglePersonMetadata | None = None

    names: list[GoogleName] = Field(default_factory=list)
    emailAddresses: list[GoogleEmailAddress] = Field(default_factory=list)
    phoneNumbers: list[GooglePhoneNumber] = Field(default_factory=list)
    addresses: list[GoogleAddress] = Field(default_factory=list)
    organizations: list[GoogleOrganization] = Field(default_factory=list)
    urls: list[GoogleUrl] = Field(default_factory=list)
    imClients: list[GoogleImClient] = Field(default_factory=list)
    biographies: list[GoogleBiography] = Field(default_factory=list)
    relations: list[GoogleRelation] = Field(default_factory=list)
    nicknames: list[GoogleNickname] = Field(default_factory=list)
    birthdays: list[GoogleBirthday] = Field(default_factory=list)
    genders: list[GoogleGender] = Field(default_factory=list)
    locales: list[GoogleLocale] = Field(default_factory=list)
