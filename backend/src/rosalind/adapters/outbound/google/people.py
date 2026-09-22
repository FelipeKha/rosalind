"""Google People API profile connector."""

from __future__ import annotations

from typing import Any

from google.oauth2.credentials import Credentials

from rosalind.auth import google as google_auth

# https://developers.google.com/people/api/rest/v1/people/get
GOOGLE_PERSON_FIELDS = (
    "addresses",
    "ageRanges",
    "biographies",
    "birthdays",
    "calendarUrls",
    "clientData",
    "coverPhotos",
    "emailAddresses",
    "events",
    "externalIds",
    "genders",
    "imClients",
    "interests",
    "locales",
    "locations",
    "memberships",
    "metadata",
    "miscKeywords",
    "names",
    "nicknames",
    "occupations",
    "organizations",
    "phoneNumbers",
    "photos",
    "relations",
    "sipAddresses",
    "skills",
    "urls",
    "userDefined",
)


def fetch_profile(credentials: Credentials) -> dict[str, Any]:
    service = google_auth.build_people_service(credentials)
    return (
        service.people()
        .get(
            resourceName="people/me",
            personFields=",".join(GOOGLE_PERSON_FIELDS),
        )
        .execute()
    )
