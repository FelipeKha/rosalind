# Personal Data Platform — Design

## 1. Vision

Build a self-hosted personal data warehouse that ingests personal data from different providers (Google, Apple, Meta, Microsoft, etc.), normalizes it into a stable canonical model, and exposes it through a client-independent API.

The platform should ultimately support multiple clients:

- CLI — first client
- AI agents
- Browser/web UI
- Native desktop/mobile applications
- Other applications integrating through the API

The central architectural principle is:

> **The data server is the product; clients are consumers of the data server.**

---

## 2. Core Architectural Principles

### 2.1 Canonical personal-data model

All provider-specific data is mapped into a common internal model.

For example:

```text
Google Contact ──┐
Apple Contact  ──┼──> Canonical Person
Meta Contact   ──┘
```

"Canonical" means the standard internal representation used by the platform, independent of the provider's original format.

The canonical model is not the raw source of truth. Raw provider data is retained separately.

### 2.2 Raw data is immutable

Every import is preserved.

A new Google Takeout is treated as another observation of the same underlying source data, not as a replacement of the previous Takeout.

This makes the canonical database rebuildable if normalization or entity-resolution logic changes.

### 2.3 Provider formats are isolated

Provider-specific formats must never leak into the canonical model.

Use:

```text
Provider export
    ↓
Provider adapter/parser
    ↓
Source representation
    ↓
Canonicalization
    ↓
Canonical model
```

Each provider adapter is independently versioned.

### 2.4 Client independence

The backend exposes an API/domain layer independent of any particular client.

Initial architecture:

```text
CLI
  │
  ▼
API / domain layer
  │
  ▼
PostgreSQL
```

Future clients use the same backend:

```text
                 Personal Data Server
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
         CLI         AI agent        Browser/App
```

The backend must not depend on the CLI's implementation.

---

# 3. Initial Technology Choices

## Backend

**Python**

Reasons:

- Excellent data-processing ecosystem
- Strong JSON/Pydantic support
- Excellent AI/LLM ecosystem
- Good HTTP/API tooling
- Fast development
- Suitable for I/O-heavy ingestion workloads
- Easy to introduce optimized components later if required

Likely stack:

- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL
- pgvector when semantic search is introduced

Do not introduce Rust initially.

Rust can be considered later for measured bottlenecks such as:

- Very large-file parsing
- Hashing
- Compression
- Encryption
- CPU-intensive transformations
- Memory-intensive local processing

## Database

**PostgreSQL**

Use PostgreSQL for:

- Canonical relational data
- Source/import metadata
- Provenance
- Full-text search
- JSONB for provider-specific information
- pgvector for semantic search when needed

Do not make a vector database the primary source of truth.

## Client

**CLI first**

The first user-facing client should be a CLI that communicates with the backend.

Potential future clients:

1. CLI
2. AI-agent interface
3. Browser/web UI
4. Desktop/mobile app

---

# 4. High-Level Architecture

```text
                       External data providers
              ┌────────────┬────────────┬────────────┐
              │            │            │            │
           Google        Apple         Meta        Others
              │            │            │
              └────────────┼────────────┘
                           ▼
                    Import / ingestion
                           │
                           ▼
                    Provider adapters
                           │
                           ▼
                 Source representation
                           │
                           ▼
                 Validation + staging
                           │
                           ▼
                  Entity resolution
                           │
                           ▼
                    Canonical model
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
          REST/API      Search/AI      CLI client
                           │
                           ├── structured retrieval
                           ├── full-text search
                           └── semantic search
```

---

# 5. Source / Import Layer

## 5.1 Source accounts

A source account represents an account at an external provider.

```sql
CREATE TYPE source_provider AS ENUM (
    'google',
    'apple',
    'meta',
    'microsoft',
    'linkedin',
    'other'
);

CREATE TABLE source_account (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    provider source_provider NOT NULL,

    account_identifier TEXT,

    display_name TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    metadata JSONB NOT NULL DEFAULT '{}'
);
```

Examples:

```text
Google personal
Google work
Apple iCloud
Microsoft work
```

---

## 5.2 Data imports

Every Takeout/export is an independent import.

```sql
CREATE TABLE data_import (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_account_id UUID NOT NULL
        REFERENCES source_account(id),

    provider TEXT NOT NULL,

    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,

    source_created_at TIMESTAMPTZ,

    status TEXT NOT NULL,

    file_hash TEXT,

    parser_name TEXT,
    parser_version TEXT,

    metadata JSONB NOT NULL DEFAULT '{}'
);
```

Example:

```text
Import A
Google
2026-09-01
parser = google_contacts
version = 2

Import B
Google
2026-09-08
parser = google_contacts
version = 2
```

---

# 6. Raw Source Records

Provider data should be preserved before canonicalization.

```sql
CREATE TABLE source_record (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    import_id UUID NOT NULL
        REFERENCES data_import(id),

    source_account_id UUID NOT NULL
        REFERENCES source_account(id),

    entity_type TEXT NOT NULL,

    provider_id TEXT NOT NULL,

    data JSONB NOT NULL,

    content_hash TEXT NOT NULL,

    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,

    UNIQUE (
        source_account_id,
        entity_type,
        provider_id
    )
);
```

The combination:

```text
source_account
entity_type
provider_id
```

is the source identity of an object.

For example:

```text
Google / contact / people/c123
```

---

# 7. Source Record Versions

Do not overwrite historical provider data.

```sql
CREATE TABLE source_record_version (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_record_id UUID NOT NULL
        REFERENCES source_record(id),

    import_id UUID NOT NULL
        REFERENCES data_import(id),

    data JSONB NOT NULL,

    content_hash TEXT NOT NULL,

    observed_at TIMESTAMPTZ NOT NULL,

    UNIQUE(source_record_id, content_hash)
);
```

This allows:

```text
Google people/c123

Version 1 — Sep 1
John Smith
john@gmail.com

Version 2 — Sep 8
John Smith
john@gmail.com
john.smith@company.com
```

If a subsequent Takeout contains exactly the same object, the content hash prevents a duplicate version.

---

# 8. Import Strategy

A new Takeout should be treated as an incremental reconciliation of observations.

For every source object:

```python
content_hash = sha256(canonical_json(source_object))
```

Then:

```python
existing = find_source_record(
    account_id,
    entity_type,
    provider_id
)

if existing is None:
    create_source_record(...)
    create_version(...)

elif existing.content_hash != content_hash:
    create_version(...)
    update_source_record(...)

else:
    # Already seen; no new version required.
    record_observation(...)
```

Important properties:

- Imports are idempotent.
- Re-importing the same Takeout does not duplicate data.
- Changed source objects create new versions.
- New source objects are added.
- Existing canonical entities are not recreated merely because a new Takeout was imported.

---

# 9. Handling Deletions

A missing object in a later Takeout must **not automatically be interpreted as deletion**.

Reasons include:

- Export incompleteness
- Provider export changes
- Filtering
- Different export options
- Actual deletion

Therefore track:

```text
last_seen_import_id
last_seen_at
```

and potentially:

```text
possibly_deleted_from_source
```

Only treat an object as definitively deleted when the source provides reliable deletion semantics.

Never delete the raw source record merely because it disappeared from an export.

---

# 10. Provider Adapter Architecture

Provider-specific parsers should be isolated and versioned.

Recommended structure:

```text
backend/
└── ingestion/
    ├── framework/
    │   ├── parser.py
    │   ├── registry.py
    │   ├── validation.py
    │   └── staging.py
    │
    ├── google/
    │   ├── contacts/
    │   │   ├── v1.py
    │   │   └── v2.py
    │   ├── gmail/
    │   └── calendar/
    │
    ├── apple/
    │   ├── contacts/
    │   ├── mail/
    │   └── calendar/
    │
    └── meta/
        ├── contacts/
        └── messages/
```

A parser should have a common interface:

```python
class Parser(Protocol):
    provider: str
    object_type: str
    version: str

    def can_parse(self, data: RawImport) -> bool:
        ...

    def parse(self, data: RawImport) -> list[SourceObject]:
        ...
```

Use a parser registry to select the correct adapter.

---

# 11. Intermediate Source Representation

Avoid going directly from provider format to canonical data.

Instead:

```text
Google JSON
    ↓
Google adapter
    ↓
Source representation
    ↓
Canonicalization
    ↓
Canonical model
```

For example:

```json
{
  "provider": "google",
  "object_type": "contact",
  "provider_id": "people/c123",

  "name": {
    "given": "John",
    "family": "Smith"
  },

  "emails": [
    {
      "address": "john@gmail.com",
      "label": "home"
    }
  ]
}
```

Apple's representation of the same contact should produce the same source-level structure.

This makes the canonicalization layer provider-independent.

---

# 12. Validation and Schema Evolution

Use Pydantic models for provider-specific formats.

Example:

```python
from pydantic import BaseModel, ConfigDict


class GoogleName(BaseModel):
    givenName: str | None = None
    familyName: str | None = None


class GoogleEmail(BaseModel):
    value: str
    type: str | None = None


class GoogleContact(BaseModel):
    model_config = ConfigDict(extra="allow")

    resourceName: str
    names: list[GoogleName] = []
    emailAddresses: list[GoogleEmail] = []
```

Important rule:

### Additive provider changes

If Google adds a field:

```text
newField
```

do not necessarily fail the import.

Preserve unknown fields.

### Breaking provider changes

If a required field disappears or the structure fundamentally changes:

```text
validation → failure
```

Do not write corrupted canonical data.

Instead quarantine the import.

---

# 13. Import State Machine

Imports should be processed through explicit stages:

```text
RECEIVED
   ↓
SCANNING
   ↓
PARSING
   ↓
VALIDATING
   ↓
STAGING
   ↓
NORMALIZING
   ↓
ENTITY_RESOLUTION
   ↓
COMMITTING
   ↓
COMMITTED
```

Failure state:

```text
VALIDATING
     ↓
QUARANTINED
```

An invalid import must never corrupt the existing canonical database.

The canonical database should only be updated after the relevant import has successfully passed validation/staging.

---

# 14. Import Health Checks

Schema validation alone is insufficient.

Calculate import statistics:

```text
Import #18

Contacts:           1,842
Emails:             82,431
Calendar events:    12,293

New contacts:       4
Modified contacts:  17

Validation errors:  0
```

Compare with previous imports.

Flag suspicious changes such as:

```text
Previous contacts: 1,842
Current contacts:      23
```

This could indicate a provider format change even if the JSON technically validates.

Suspicious imports should be quarantined or require explicit approval rather than silently replacing good data.

---

# 15. Golden Test Fixtures

Maintain representative real-world export fixtures:

```text
tests/
└── fixtures/
    ├── google/
    │   ├── contacts/
    │   │   ├── export_2025.json
    │   │   └── export_2026.json
    │   ├── gmail/
    │   └── calendar/
    │
    ├── apple/
    └── meta/
```

Test both:

1. Provider parsing
2. Expected canonical output

Example:

```python
def test_google_contacts_parser():
    raw = load_fixture(
        "google/contacts/export_2026.json"
    )

    contacts = parse_google_contacts(raw)

    assert len(contacts) == 123
```

And:

```python
def test_google_contact_normalization():
    raw = load_fixture(...)

    result = normalize_google_contacts(raw)

    assert result == load_expected(
        "google/contact_expected.json"
    )
```

These tests are effectively compatibility contracts for each provider.

---

# 16. Canonical Identity Model

Distinguish **source identity** from **canonical identity**.

Source identity:

```text
Google / people/c123
Apple / ABC123
```

Canonical identity:

```text
Person / 123
```

Mapping:

```text
Google people/c123 ──┐
                     ├──> Person 123
Apple ABC123 ────────┘
```

This allows entity-resolution logic to improve without changing the raw source data.

---

# 17. Canonical People Model

## Person

```sql
CREATE TABLE person (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    given_name TEXT,
    family_name TEXT,

    display_name TEXT,

    birth_date DATE,

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Email address

```sql
CREATE TABLE email_address (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    address TEXT NOT NULL,

    normalized_address TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(normalized_address)
);
```

## Person/email relationship

```sql
CREATE TABLE person_email (
    person_id UUID NOT NULL
        REFERENCES person(id)
        ON DELETE CASCADE,

    email_id UUID NOT NULL
        REFERENCES email_address(id)
        ON DELETE CASCADE,

    label TEXT,

    is_primary BOOLEAN DEFAULT false,

    confidence NUMERIC(4,3),

    PRIMARY KEY (person_id, email_id)
);
```

## Phone

```sql
CREATE TABLE phone_number (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    number TEXT NOT NULL,

    normalized_number TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(normalized_number)
);

CREATE TABLE person_phone (
    person_id UUID NOT NULL
        REFERENCES person(id),

    phone_id UUID NOT NULL
        REFERENCES phone_number(id),

    label TEXT,

    is_primary BOOLEAN DEFAULT false,

    confidence NUMERIC(4,3),

    PRIMARY KEY (person_id, phone_id)
);
```

---

# 18. Identity Model

```sql
CREATE TABLE identity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    person_id UUID NOT NULL
        REFERENCES person(id),

    provider source_provider NOT NULL,

    provider_user_id TEXT,

    username TEXT,

    profile_url TEXT,

    metadata JSONB NOT NULL DEFAULT '{}',

    UNIQUE(provider, provider_user_id)
);
```

Example:

```text
Person 123
    ├── Google identity
    ├── Apple identity
    ├── LinkedIn identity
    └── Meta identity
```

---

# 19. Provenance

Every canonical entity should be traceable back to source data.

```sql
CREATE TABLE entity_source (
    source_record_id UUID NOT NULL
        REFERENCES source_record(id),

    entity_type TEXT NOT NULL,

    entity_id UUID NOT NULL,

    match_method TEXT,

    confidence NUMERIC(4,3),

    PRIMARY KEY (
        source_record_id,
        entity_type,
        entity_id
    )
);
```

This allows the system to answer:

> "Why do we believe this is John Smith's email address?"

Example lineage:

```text
Person 123
    │
    └── email = john@gmail.com
             │
             ├── Google contact people/c123
             └── Email message 83921
```

---

# 20. Email Model

Separate email messages from participants.

## Email thread

```sql
CREATE TABLE email_thread (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    subject_normalized TEXT,

    first_message_at TIMESTAMPTZ,

    last_message_at TIMESTAMPTZ,

    message_count INTEGER NOT NULL DEFAULT 0
);
```

## Email message

```sql
CREATE TABLE email_message (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    internet_message_id TEXT,

    subject TEXT,

    body_text TEXT,

    body_html TEXT,

    sent_at TIMESTAMPTZ,

    received_at TIMESTAMPTZ,

    thread_id UUID
        REFERENCES email_thread(id),

    in_reply_to_id UUID,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    metadata JSONB NOT NULL DEFAULT '{}'
);
```

## Participants

```sql
CREATE TYPE email_participant_type AS ENUM (
    'from',
    'to',
    'cc',
    'bcc',
    'reply_to'
);

CREATE TABLE email_participant (
    email_id UUID NOT NULL
        REFERENCES email_message(id)
        ON DELETE CASCADE,

    email_address_id UUID NOT NULL
        REFERENCES email_address(id),

    participant_type email_participant_type NOT NULL,

    position INTEGER,

    PRIMARY KEY (
        email_id,
        email_address_id,
        participant_type
    )
);
```

## Resolved person relationships

```sql
CREATE TABLE email_person (
    email_id UUID NOT NULL
        REFERENCES email_message(id),

    person_id UUID NOT NULL
        REFERENCES person(id),

    role email_participant_type NOT NULL,

    confidence NUMERIC(4,3),

    PRIMARY KEY (email_id, person_id, role)
);
```

---

# 21. Calendar Model

## Calendar

```sql
CREATE TABLE calendar (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_account_id UUID
        REFERENCES source_account(id),

    name TEXT NOT NULL,

    description TEXT,

    timezone TEXT,

    provider_calendar_id TEXT,

    metadata JSONB NOT NULL DEFAULT '{}'
);
```

## Event

```sql
CREATE TABLE calendar_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    calendar_id UUID NOT NULL
        REFERENCES calendar(id),

    provider_event_id TEXT,

    title TEXT,

    description TEXT,

    location TEXT,

    start_at TIMESTAMPTZ,

    end_at TIMESTAMPTZ,

    all_day BOOLEAN NOT NULL DEFAULT false,

    status TEXT,

    recurrence_rule TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    metadata JSONB NOT NULL DEFAULT '{}'
);
```

## Event participants

```sql
CREATE TYPE event_participant_role AS ENUM (
    'organizer',
    'required',
    'optional',
    'resource'
);

CREATE TABLE event_participant (
    event_id UUID NOT NULL
        REFERENCES calendar_event(id)
        ON DELETE CASCADE,

    person_id UUID
        REFERENCES person(id),

    email_address_id UUID
        REFERENCES email_address(id),

    role event_participant_role,

    response_status TEXT,

    PRIMARY KEY (
        event_id,
        person_id,
        email_address_id
    )
);
```

An event participant may initially be only an email address and later be resolved to a Person.

---

# 22. Temporal Data

Important data should preserve history rather than only current state.

For example:

```text
salary
    €70k — Jan 2024 → Dec 2024
    €80k — Jan 2025 → present
```

Distinguish:

- event time / validity time
- database observation time

This allows future queries such as:

> "What did we know about this person at a particular point in time?"

---

# 23. AI / Semantic Layer

AI-derived information should be separate from canonical facts.

Example:

```sql
CREATE TABLE ai_entity_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    entity_type TEXT NOT NULL,

    entity_id UUID NOT NULL,

    summary TEXT NOT NULL,

    model TEXT NOT NULL,

    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    source_hash TEXT NOT NULL
);
```

Never allow AI-generated summaries or classifications to silently overwrite canonical facts.

AI-derived data should record:

- model
- generation timestamp
- source/dependency hash
- optionally prompt/version metadata

---

# 24. Embeddings

When semantic retrieval is required:

```sql
CREATE EXTENSION vector;

CREATE TABLE embedding (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    entity_type TEXT NOT NULL,

    entity_id UUID NOT NULL,

    content TEXT NOT NULL,

    embedding vector(1536),

    model TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Potential embedded objects:

- Person summaries
- Email threads
- Individual emails
- Calendar events
- Documents

Embeddings are an **index/derived representation**, not the source of truth.

---

# 25. Agent-Oriented API

Do not expose unrestricted SQL to AI agents.

Expose semantic operations such as:

```text
find_person(query)
get_person(person_id)
get_person_context(person_id)

get_conversation(person_id)
get_recent_interactions(person_id)

get_calendar_history(person_id)

search_personal_data(query)
find_people_related_to(person_id)
```

The implementation can combine:

```text
SQL
+
full-text search
+
vector search
+
relationship traversal
```

The agent should not need to know how the underlying data is stored.

---

# 26. Agent Context / Projections

Do not return huge raw datasets to an AI agent.

Create compact, agent-oriented projections.

Example:

```json
{
  "person": {
    "id": "123",
    "name": "John Smith",
    "emails": [
      "john@gmail.com",
      "john@company.com"
    ]
  },

  "relationship": {
    "first_seen": "2019-04-12",
    "last_interaction": "2026-09-03",
    "email_count": 184,
    "meeting_count": 27
  },

  "recent_emails": [
    {
      "date": "2026-09-03",
      "subject": "Project update",
      "summary": "..."
    }
  ],

  "upcoming_meetings": [
    {
      "date": "2026-09-15",
      "title": "Project review"
    }
  ]
}
```

The storage model is optimized for data integrity and querying.

The agent API is optimized for reasoning and token efficiency.

---

# 27. Data Lineage

The system should make it possible to trace information through:

```text
Provider export
    ↓
Raw source record
    ↓
Source record version
    ↓
Canonical entity
    ↓
AI-derived representation
```

For example:

```text
John Smith
    │
    ├── email: john@gmail.com
    │       ├── Google contact
    │       └── Email messages
    │
    └── phone: +33...
            └── Apple contact
```

This is essential for:

- Debugging
- Trust
- AI citations
- Reprocessing
- Entity-resolution improvements

---

# 28. Non-Negotiable Invariants

The following should be treated as architectural invariants:

1. **Raw imports are immutable.**
2. **Canonical data is derived from source observations.**
3. **Re-importing the same data is idempotent.**
4. **Provider IDs are never used as canonical IDs.**
5. **Provider-specific formats never leak into the canonical model.**
6. **Every provider adapter is independently versioned.**
7. **Provider schema changes cannot corrupt canonical data.**
8. **Failed imports are quarantined rather than partially committed.**
9. **Canonical entities maintain provenance.**
10. **AI-derived information never silently overwrites canonical facts.**
11. **The backend is independent of any client.**
12. **The canonical database should be rebuildable from retained source data.**

---

# 29. Initial Project Scope

Start with three Google data domains:

```text
Google Takeout
    │
    ├── Contacts
    ├── Gmail
    └── Calendar
```

Build:

### Phase 1 — Infrastructure

- PostgreSQL
- SQLAlchemy
- Alembic
- FastAPI
- CLI
- Import tracking
- Raw source storage

### Phase 2 — Google Contacts

- Takeout parser
- Versioned parser
- Pydantic validation
- Source records
- Canonical Person
- Email addresses
- Phones
- Entity resolution
- Provenance

### Phase 3 — Gmail

- Messages
- Threads
- Participants
- Person resolution
- Incremental reconciliation

### Phase 4 — Calendar

- Calendars
- Events
- Participants
- Person resolution

### Phase 5 — Search

- PostgreSQL full-text search
- Cross-domain queries

### Phase 6 — AI

- Agent-oriented API
- AI summaries
- Embeddings
- Semantic search
- Context projections

### Phase 7 — Additional clients

```text
CLI
 ↓
AI agent
 ↓
Browser
 ↓
Desktop/mobile application
```

---

# 30. Guiding Example

The architecture should ultimately make this possible:

```text
User:
"What is my relationship with John Smith?"
```

The system should be able to combine:

```text
Person
    ↓
Identity
    ↓
Email addresses
    ↓
Email messages / threads
    ↓
Calendar events
    ↓
Interaction history
    ↓
AI-generated summary
```

and produce a compact, explainable answer with provenance.

The goal is therefore not simply to build a database of personal data.

The goal is to build a **reliable personal-data substrate that both traditional software and AI agents can query and reason over.**
