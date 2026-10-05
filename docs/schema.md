# Schema

This is the reference for Rosalind's Postgres schema. The models are the
source of truth for this document — they live under
`backend/src/rosalind/adapters/outbound/persistence/models/` and the
migrations under
`backend/src/rosalind/adapters/outbound/migrations/versions/`. If the two ever
disagree, the models (and the migration they produce) win; fix this document.

Data is split into four schemas by role:

| Schema | Role | Delete semantics |
|---|---|---|
| `raw` | Immutable provider evidence | Never deleted by canonical operations |
| `core` | Canonical model + provenance | Cascades to dependent facts, never to `raw` |
| `agent` | Derived read models (views) | None — read-only projection |
| `public` (default) | Operational: imports, source accounts, OAuth, accounts | Domain-specific (below) |

See [`DESIGN.md`](../DESIGN.md) §6 for the layering rationale and §7 for the
canonical-model concepts.

## Conventions

- **Primary keys** are `uuid` (`sa.Uuid`), generated in Python
  (`uuid.uuid4`), never by the database.
- **Timestamps** are `timestamptz`, written in UTC. `created_at` /
  `updated_at` are set by `utcnow` and `onupdate`, not by a trigger.
- **`metadata` / `metadata_`** columns are `JSONB` with a `dict` default;
  `metadata_` is the Python attribute name for the column actually named
  `metadata` (avoiding SQLAlchemy's reserved `metadata`).
- **Text** fields use `text` (unbounded) unless an explicit `varchar(n)` is
  shown (used for short provider/state strings).
- **`is_primary`** is Rosalind's resolved choice (exactly one per fact
  category per person), enforced by a *partial* unique index `… WHERE
  is_primary`. `source_primary`/`source_verified` are provider claims and live
  on the assertion instead — they are allowed to disagree with `is_primary`.
- **NULLS NOT DISTINCT** is used on value-uniqueness constraints so two
  partial dates (e.g. no `day`) deduplicate correctly.

---

## `raw` — immutable evidence

```text
raw.source_record
```

One immutable row per *distinct observed payload*, keyed by
`(source_account, resource_type, external_id, payload_sha256)`. Payloads are
persisted **before** validation or canonicalization; a parse failure never
discards the original.

### `raw.source_record`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `source_account_id` | uuid | no | FK → `source_account.id` `ON DELETE RESTRICT`; indexed |
| `import_id` | uuid | yes | FK → `imports.id` `ON DELETE SET NULL`; indexed |
| `resource_type` | text | no | provider object kind (e.g. `person`) |
| `external_id` | text | no | provider's id for this object (never canonical) |
| `source_etag` | text | yes | provider etag, if any |
| `source_updated_at` | timestamptz | yes | provider's own modification time |
| `observed_at` | timestamptz | no | when Rosalind recorded it |
| `payload` | jsonb | yes | canonical JSON of the full provider payload (JSON providers) |
| `payload_sha256` | text | no | SHA-256 of the payload |
| `payload_uri` | text | yes | object-storage key holding the payload bytes (byte providers, e.g. email messages) |

Constraints / indexes:

- `uq_source_record_snapshot` unique on
  `(source_account_id, resource_type, external_id, payload_sha256)` — this is
  what makes re-importing an identical payload a no-op.
- `ix_source_record_source_account_id`, `ix_source_record_import_id`.

`import_id` is the hook `process <import-id>` uses to select the records to
canonicalize. Deletion of an import nulls it (records survive).

---

## `core` — canonical model and provenance

Four kinds of table:

1. **Entity** — `person` (bare, no attribute columns).
2. **Identity** — `source_identity` (person ↔ external identity).
3. **Assertion** — `source_assertion` (a statement observed in one raw
   record).
4. **Fact** — `person_name`, `person_email`, `person_phone`, `person_address`,
   `person_organization`, `person_date`, `person_gender`, `person_locale`,
   `person_url`, `person_im`, `person_note`, `person_relation`,
   `person_nickname` (Rosalind's resolved value) plus `person_*_assertion`
   link tables (one fact ↔ many supporting assertions).

```text
Person             = canonical real-world entity
Source identity    = that entity's identity within one external source
Source assertion   = a statement observed in one raw source record
Canonical fact     = Rosalind's current resolved representation of an attribute
```

### `core.person`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `created_at` | timestamptz | no | |
| `updated_at` | timestamptz | no | |

Deliberately bare: attribute values live only in the fact tables, selected by
`is_primary`, so a value is never duplicated between the entity and its facts.

### `core.source_identity`

Maps a person to an external identity, scoped to a source account. Provider
IDs are never canonical: Google's `resourceName` can change, so the numeric
source id is held in `external_id` and the full name in `resource_name`.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `source_account_id` | uuid | no | FK → `source_account.id` `ON DELETE RESTRICT` |
| `source_type` | text | no | e.g. `GOOGLE_PEOPLE` |
| `external_id` | text | no | provider-scoped id |
| `resource_name` | text | yes | provider's full opaque name |

`uq_source_identity_account_type_external` unique on
`(source_account_id, source_type, external_id)`. The same `(source_type,
external_id)` may mean different people under different source accounts.

### `core.source_assertion`

Field-level provenance for a single value within one raw record. It survives
person/fact deletion (only removed together with its `source_record`), so the
audit trail is preserved even after a canonical entity is deleted or merged.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `source_record_id` | uuid | no | FK → `raw.source_record.id` `ON DELETE CASCADE`; indexed |
| `source_identity_id` | uuid | yes | FK → `core.source_identity.id` `ON DELETE RESTRICT`; indexed |
| `field_path` | text | no | dotted path into the payload (e.g. `names[0].displayName`) |
| `source_primary` | boolean | yes | provider's "is primary" claim |
| `source_verified` | boolean | yes | provider's "is verified" claim |
| `metadata` | jsonb | no | provider-specific extras |

`uq_source_assertion_record_field` unique on `(source_record_id, field_path)`.

### `core.person_name`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `display_name` | text | yes | |
| `given_name` | text | yes | |
| `family_name` | text | yes | |
| `middle_name` | text | yes | |
| `name_prefix` | text | yes | honorific prefix (e.g. `Dr.`) |
| `name_suffix` | text | yes | honorific suffix (e.g. `Jr.`) |
| `previous_family_name` | text | yes | |
| `phonetic_given_name` | text | yes | |
| `phonetic_middle_name` | text | yes | |
| `phonetic_family_name` | text | yes | |
| `phonetic_full_name` | text | yes | |
| `is_primary` | boolean | no | default `false` |

- `uq_person_name_one_primary` partial unique on `(person_id) WHERE is_primary`.
- `uq_person_name_value` unique on `(person_id, display_name, given_name,
  family_name, middle_name, name_prefix, name_suffix)` `NULLS NOT DISTINCT`.
  `previous_family_name` and the `phonetic_*` columns are auxiliary and not part
  of value-uniqueness.

### `core.person_email`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `email` | text | no | as observed |
| `email_normalized` | text | no | lowercased canonical form |
| `type` | text | yes | e.g. `home`, `work` |
| `is_primary` | boolean | no | default `false` |
| `is_verified` | boolean | no | default `false` |

- `uq_person_email_person_normalized` unique on `(person_id, email_normalized)`.
- `ix_person_email_normalized` on `(email_normalized)` — the lookup key for
  identity resolution.
- `uq_person_email_one_primary` partial unique on `(person_id) WHERE is_primary`.

### `core.person_date`

A whole or partial date (year/month/day independently nullable — no
duplication of year/month/day, and precision is preserved).

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `date_type` | text | no | default `'birthday'` |
| `year` | integer | yes | |
| `month` | integer | yes | |
| `day` | integer | yes | |
| `is_primary` | boolean | no | default `false` |

- Check constraints: `ck_person_date_month` (`month` in 1–12 or null),
  `ck_person_date_day` (`day` in 1–31 or null), `ck_person_date_precision`
  (`day` null unless `month` present).
- `uq_person_date_one_primary` partial unique on `(person_id, date_type)
  WHERE is_primary`.
- `uq_person_date_value` unique on `(person_id, date_type, year, month, day)`
  `NULLS NOT DISTINCT`.

### `core.person_gender`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `value` | text | no | |
| `is_primary` | boolean | no | default `false` |

- `uq_person_gender_one_primary` partial unique on `(person_id) WHERE is_primary`.
- `uq_person_gender_value` unique on `(person_id, value)`.

### `core.person_locale`

Identical shape to `core.person_gender`:

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `value` | text | no | |
| `is_primary` | boolean | no | default `false` |

- `uq_person_locale_one_primary` partial unique on `(person_id) WHERE is_primary`.
- `uq_person_locale_value` unique on `(person_id, value)`.

### `core.person_phone`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `value` | text | no | as observed |
| `value_normalized` | text | no | digits (+ leading `+`) comparison key |
| `type` | text | yes | e.g. `home`, `work`, `mobile`, `fax` |
| `is_primary` | boolean | no | default `false` |
| `is_verified` | boolean | no | default `false` |

- `uq_person_phone_person_normalized` unique on `(person_id, value_normalized)`.
- `uq_person_phone_one_primary` partial unique on `(person_id) WHERE is_primary`.

### `core.person_address`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `type` | text | yes | e.g. `home`, `work`, `other` |
| `formatted` | text | yes | provider's unstructured rendering |
| `street` | text | yes | |
| `city` | text | yes | |
| `region` | text | yes | state/province |
| `postal_code` | text | yes | |
| `country` | text | yes | |
| `country_code` | text | yes | ISO 3166-1 alpha-2 |
| `is_primary` | boolean | no | default `false` |

- `uq_person_address_value` unique on `(person_id, type, formatted, street, city,
  region, postal_code, country, country_code)` `NULLS NOT DISTINCT`.
- `uq_person_address_one_primary` partial unique on `(person_id) WHERE is_primary`.

### `core.person_organization`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `name` | text | yes | |
| `department` | text | yes | |
| `title` | text | yes | |
| `type` | text | yes | e.g. `work`, `school` |
| `current` | boolean | yes | whether this is the current organization |
| `start_year` / `start_month` / `start_day` | integer | yes | partial date |
| `end_year` / `end_month` / `end_day` | integer | yes | partial date |
| `phonetic_name` | text | yes | |
| `is_primary` | boolean | no | default `false` |

- Check constraints mirror `person_date` (`month` 1–12, `day` requires `month`).
- `uq_person_organization_value` unique on `(person_id, name, department, title,
  type, start_year, start_month, start_day)` `NULLS NOT DISTINCT`.
- `uq_person_organization_one_primary` partial unique on `(person_id) WHERE is_primary`.

### `core.person_url`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `value` | text | no | |
| `type` | text | yes | e.g. `home`, `work` |
| `is_primary` | boolean | no | default `false` |

- `uq_person_url_value` unique on `(person_id, value)`.
- `uq_person_url_one_primary` partial unique on `(person_id) WHERE is_primary`.

### `core.person_im`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `service` | text | yes | protocol/service (e.g. `googleTalk`, `skype`) |
| `username` | text | no | |
| `type` | text | yes | |
| `is_primary` | boolean | no | default `false` |

- `uq_person_im_value` unique on `(person_id, service, username, type)`
  `NULLS NOT DISTINCT`.
- `uq_person_im_one_primary` partial unique on `(person_id) WHERE is_primary`.

### `core.person_note`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `value` | text | no | |
| `content_type` | text | yes | e.g. `text/plain`, `text/html` |
| `is_primary` | boolean | no | default `false` |

- `uq_person_note_value` unique on `(person_id, value)`.
- `uq_person_note_one_primary` partial unique on `(person_id) WHERE is_primary`.

### `core.person_relation`

A directed edge from a person to another person. `type` describes what
`related_person` is to `person_id` (e.g. a `spouse` relation on A pointing at B
means "B is A's spouse"). The target resolves over time: initially only
`related_person_name` is set, and `related_person_id` is filled by a later
resolution pass once an unambiguous person matches. It has **no** `is_primary` —
relations are a set of edges, not an attribute with a single primary value.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `related_person_id` | uuid | yes | FK → `core.person.id` `ON DELETE SET NULL`; indexed |
| `related_person_name` | text | yes | asserted string, kept after resolution |
| `type` | text | no | e.g. `spouse`, `child`, `mother`, `manager` |

- `ck_person_relation_target` check: `related_person_id` or
  `related_person_name` present.
- `uq_person_relation_value` unique on `(person_id, type, related_person_name)`
  `NULLS NOT DISTINCT`. `related_person_id` is resolution state, not identity:
  resolving an edge mutates it without changing the fact's uniqueness key, so a
  re-import of the source record remains idempotent.

### `core.person_nickname`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `person_id` | uuid | no | FK → `core.person.id` `ON DELETE CASCADE`; indexed |
| `value` | text | no | |
| `type` | text | yes | |
| `is_primary` | boolean | no | default `false` |

- `uq_person_nickname_value` unique on `(person_id, value)`.
- `uq_person_nickname_one_primary` partial unique on `(person_id) WHERE is_primary`.

### Link tables — `person_*_assertion`

Thirteen link tables (`person_name_assertion`, `person_email_assertion`,
`person_phone_assertion`, `person_address_assertion`,
`person_organization_assertion`, `person_date_assertion`,
`person_gender_assertion`, `person_locale_assertion`, `person_url_assertion`,
`person_im_assertion`, `person_note_assertion`, `person_relation_assertion`,
`person_nickname_assertion`), each with the same shape:

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `assertion_id` | uuid | no | PK; FK → `core.source_assertion.id` `ON DELETE CASCADE` |
| `person_<x>_id` | uuid | no | FK → the fact table `ON DELETE CASCADE`; indexed |

`assertion_id` is the PK (one assertion supports one fact of a given kind);
the fact column is indexed so a fact can list all supporting assertions.

### Worked example — Google People `Person`

For one imported Google contact:

1. The full payload is stored once in `raw.source_record` (`resource_type =
   'person'`, `external_id` = the numeric Google id).
2. A `core.source_identity` row links a `core.person` to
   `(source_account_id, 'GOOGLE_PEOPLE', external_id)`.
3. Each field the payload asserts becomes a `core.source_assertion` row
   (`field_path` like `names[0].displayName`, `source_primary`/`source_verified`
   copied from Google's `primary`/`metadata.verified`).
4. Canonicalization upserts the resolved facts (`person_name`, `person_email`,
   …), setting `is_primary` where appropriate, and links each fact back to its
   supporting assertions via the `person_*_assertion` tables.

Re-importing the same payload is a no-op because
`uq_source_record_snapshot` and the fact value-uniqueness constraints absorb
duplicates.

---

## `agent` — derived read models

The `agent` schema currently holds one database view. Views are optimized for
compact, predictable, low-context responses; they are **not** sources of
truth and carry no integrity guarantees.

### `agent.person_profile`

Flattens each `core.person` with its primary name, email, gender, locale, and
birthday (all `is_primary`; date restricted to `date_type = 'birthday'`):

```text
person_id, display_name, given_name, family_name,
primary_email, email_verified, gender, locale,
birth_year, birth_month, birth_day
```

It is the backing read model for the `PersonProfile` value object
(`application/read_models.py`) used by REST and MCP. It is not (yet) used to
answer arbitrary SQL — application services project it through typed value
objects.

---

## `public` (default) — operational tables

These support ingestion and identity, not the canonical model itself.

### `source_account`

A connection to an external data holder (e.g. a Google account). **Not** a
Rosalind `account` (a user) — see [`auth.md`](auth.md).

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `provider` | varchar(50) | no | e.g. `google` |
| `name` | text | yes | human-facing CLI slug; unique |
| `account_identifier` | text | yes | provider-scoped account id |
| `display_name` | text | yes | |
| `created_at` | timestamptz | no | |
| `metadata` | jsonb | no | default `{}` |

- `uq_source_account_provider_identifier` unique on `(provider,
  account_identifier)` — the immutable provider identity.
- `uq_source_account_name` unique on `(name)`.

### `oauth_credentials`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `source_account_id` | uuid | no | FK → `source_account.id` `ON DELETE CASCADE`; indexed |
| `provider` | varchar(50) | no | |
| `token_type` | text | no | default `'Bearer'` |
| `access_token_encrypted` | text | no | encrypted at rest |
| `refresh_token_encrypted` | text | yes | encrypted at rest |
| `scope` | text | yes | |
| `expires_at` | timestamptz | yes | |
| `created_at` / `updated_at` | timestamptz | no | |

`uq_oauth_credentials_account_provider` unique on `(source_account_id,
provider)`. Tokens are stored encrypted; never log them.

### `oauth_auth_request`

Tracks an in-flight OAuth authorization (state machine across the provider
callback round-trip).

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `state` | varchar(128) | no | PK |
| `source_account_id` | uuid | no | FK → `source_account.id` `ON DELETE CASCADE`; indexed |
| `source_name` | text | yes | requested source name, preserved across callback |
| `status` | text | no | default `'pending'` |
| `code_verifier` | text | yes | PKCE code verifier |
| `created_at` | timestamptz | no | |
| `expires_at` | timestamptz | no | |
| `consumed_at` | timestamptz | yes | |

### `imports`

A discrete ingestion job/dataset bound to a source account. Tracks two
independent dimensions: `ingestion_status` (was the data brought in?) and
`processing_status` (has it been canonicalized?).

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `source_account_id` | uuid | yes | FK → `source_account.id` `ON DELETE SET NULL`; indexed |
| `type` | text | no | import type |
| `ingestion_status` | text | no | |
| `processing_status` | text | no | default `'pending'` |
| `created_at` | timestamptz | no | |
| `completed_at` | timestamptz | yes | |
| `file_count` | bigint | no | default `0` |
| `total_size` | bigint | no | default `0` |
| `import_hash` | text | yes | |

### `import_files`

One row per uploaded file in an import.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `import_id` | uuid | no | FK → `imports.id` `ON DELETE CASCADE`; indexed |
| `path` | text | no | |
| `format` | text | yes | |
| `size` | bigint | no | default `0` |
| `modified_at` | timestamptz | yes | |
| `sha256` | text | no | |
| `storage_key` | text | no | object-storage key for the bytes |

`uq_import_files_import_id_path` unique on `(import_id, path)`.

### `account`

Rosalind's own notion of a user. See [`auth.md`](auth.md) for the full
account/identity model.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `self_person_id` | uuid | yes | FK → `core.person.id` `ON DELETE SET NULL`; set explicitly, never inferred |
| `created_at` | timestamptz | no | |
| `updated_at` | timestamptz | no | |

### `account_identity`

A login from an identity provider, keyed by `(issuer, subject)`.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `account_id` | uuid | no | FK → `account.id` `ON DELETE CASCADE`; indexed |
| `issuer` | text | no | IdP issuer |
| `subject` | text | no | IdP-scoped subject claim |
| `created_at` | timestamptz | no | |
| `last_seen_at` | timestamptz | no | |

`uq_account_identity_issuer_subject` unique on `(issuer, subject)` — accounts
are identified only by this pair, never by email or profile claims.

---

## Deletion semantics

Deletion differs by layer and is enforced by the FK `ON DELETE` actions above:

- **Deleting a `core.person`** cascades to `source_identity`, all fact rows,
  and their link rows — but `source_assertion` rows survive (their
  `source_record` is `RESTRICT`-held) and `raw.source_record` is untouched.
- **Deleting a `raw.source_record`** cascades to its `source_assertion`s but
  not to canonical facts that happen to lose their only supporting evidence;
  that reconciliation is a deliberate later decision, not a cascade.
- **Deleting a `source_account`** is `RESTRICT`-blocked while any
  `source_identity` or `raw.source_record` references it.
- **Deleting an `import`** nulls `imports`' own `source_account_id`
  (SET NULL) and `raw.source_record.import_id`, and cascades to
  `import_files`; raw records survive.

See `DESIGN.md` §7 for the rationale.
