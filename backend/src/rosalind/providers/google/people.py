"""Google People API profile connector."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session

from rosalind.auth import google as google_auth
from rosalind.auth import service as auth_service

ALL_PERSON_FIELDS = (
    "addresses,ageRanges,biographies,birthdays,calendarUrls,clientData,"
    "coverPhotos,emailAddresses,events,externalIds,genders,imClients,"
    "interests,locales,locations,memberships,metadata,miscKeywords,names,"
    "nicknames,occupations,organizations,phoneNumbers,photos,relations,"
    "sipAddresses,skills,urls,userDefined"
)


@dataclass
class ProfileImportResult:
    status: str
    account: str | None
    display_name: str | None
    fetched_at: datetime


def fetch_profile(credentials: Credentials) -> dict[str, Any]:
    service = google_auth.build_people_service(credentials)
    return (
        service.people()
        .get(resourceName="people/me", personFields=ALL_PERSON_FIELDS)
        .execute()
    )


def import_profile(db: Session) -> ProfileImportResult:
    account, credentials = auth_service.load_credentials(db, "google")
    person = fetch_profile(credentials)

    display_name = _display_name(person)
    if display_name:
        account.display_name = display_name
        db.commit()

    return ProfileImportResult(
        status="success",
        account=account.account_identifier,
        display_name=display_name or account.display_name,
        fetched_at=datetime.now(UTC),
    )


def _display_name(person: dict[str, Any]) -> str | None:
    names = person.get("names") or []
    if names and names[0].get("displayName"):
        return names[0]["displayName"]
    return None
