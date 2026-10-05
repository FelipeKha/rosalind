"""Google People API connector."""

from __future__ import annotations

from typing import Any

from google.oauth2.credentials import Credentials

from rosalind.adapters.outbound.google import auth as google_auth
from rosalind.application.ports.providers import ContactsFetch, ProviderCredentials

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

# https://developers.google.com/people/api/rest/v1/people.connections/list
GOOGLE_CONTACTS_SORT_ORDER = "LAST_MODIFIED_ASCENDING"
GOOGLE_CONTACTS_PAGE_SIZE = 1000


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


def fetch_contacts(credentials: Credentials) -> ContactsFetch:
    """Fetch all of the user's contacts, paginating and capturing the sync token.

    ``requestSyncToken=True`` makes the final page return ``nextSyncToken``,
    establishing the baseline for a later incremental sync. The token is only
    valid with the same request parameters, so those are returned alongside it
    in ``sync_parameters``.
    """
    service = google_auth.build_people_service(credentials)
    request = (
        service.people()
        .connections()
        .list(
            resourceName="people/me",
            personFields=",".join(GOOGLE_PERSON_FIELDS),
            pageSize=GOOGLE_CONTACTS_PAGE_SIZE,
            sortOrder=GOOGLE_CONTACTS_SORT_ORDER,
            requestSyncToken=True,
        )
    )

    contacts: list[dict[str, Any]] = []
    next_sync_token: str | None = None
    while request is not None:
        response = request.execute()
        contacts.extend(response.get("connections") or [])
        next_sync_token = response.get("nextSyncToken") or next_sync_token
        request = service.people().connections().list_next(request, response)

    return ContactsFetch(
        contacts=tuple(contacts),
        next_sync_token=next_sync_token,
        sync_parameters={
            "person_fields": list(GOOGLE_PERSON_FIELDS),
            "sort_order": GOOGLE_CONTACTS_SORT_ORDER,
        },
    )


class GooglePeopleGateway:
    """``PeopleGateway`` implementation backed by the Google People API."""

    def fetch_profile(self, credentials: ProviderCredentials) -> dict[str, Any]:
        return fetch_profile(google_auth._to_google_credentials(credentials))

    def fetch_contacts(self, credentials: ProviderCredentials) -> ContactsFetch:
        return fetch_contacts(google_auth._to_google_credentials(credentials))
