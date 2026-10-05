# Google provider

Ingestion of Google contacts via the Google People API.

## Source

The `google` source is a connection to a Google account, established through
OAuth 2.0 (authorization code + PKCE). The scopes requested at connect time
live in `adapters/outbound/google/auth.py` (`GOOGLE_SCOPES`) and include:

- `https://www.googleapis.com/auth/contacts.readonly`
- `https://www.googleapis.com/auth/contacts.other.readonly`
- the `user.*`/`profile.*` read scopes used by the profile fetch

## Endpoints

| Purpose | Method | Resource |
|---|---|---|
| Own profile (`people/me`) | `people.get` | `resourceName=people/me` |
| All contacts | `people.connections.list` | `resourceName=people/me` |

The contact list is fetched with `personFields` set to the full
`GOOGLE_PERSON_FIELDS` mask, `sortOrder=LAST_MODIFIED_ASCENDING`, `pageSize=1000`,
and `requestSyncToken=True`.

## Contact import (`--type api`)

`ProcessingService.import_api_contacts` (backed by
`GooglePeopleGateway.fetch_contacts`) paginates through `connections.list` and
ingests each returned `Person` through the same raw-first → canonicalize
pipeline used everywhere else. Each contact's payload is persisted to
`raw.source_record` before parsing; a contact that fails to parse or
canonicalize is quarantined per-record (its raw evidence is retained) without
aborting the rest of the import.

## Incremental sync baseline

The initial import requests a sync token (`requestSyncToken=True`) so the
response's `nextSyncToken` can be persisted and reused for a later delta sync
rather than a fresh full import. The token is stored on the source account:

```json
source_account.metadata = {
  "google": {
    "sync_token": "<nextSyncToken>",
    "sync_parameters": {
      "person_fields": ["names", "emailAddresses", "..."],
      "sort_order": "LAST_MODIFIED_ASCENDING"
    }
  }
}
```

`sync_parameters` records the exact request parameters the token was issued
for — Google requires a subsequent `syncToken` request to use the same
`personFields`, `sortOrder`, and `requestMask.includeField`. Consuming the
token (incremental `syncToken` requests) is not yet implemented.

## Idempotency

Re-importing contacts is idempotent: `raw.source_record` deduplicates on
`(source_account_id, resource_type, external_id, payload_sha256)`, and the
canonical fact tables deduplicate on their value-uniqueness constraints. A
Google `resourceName` can change over time; the numeric source id is held in
`source_identity.external_id` while the full `resourceName` is retained in
`resource_name`.
