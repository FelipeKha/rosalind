# Rosalind — Design

**Project:** Rosalind

---

# 1. Vision

Build a self-hosted personal data warehouse that ingests personal data from different providers (Google, Apple, Meta, Microsoft, etc.), normalizes it into a stable canonical model, and exposes it through a client-independent API.

The platform should ultimately support multiple clients:

* CLI — first client
* AI agents
* Browser/web UI
* Native desktop/mobile applications
* Other applications integrating through the API

The central architectural principle is:

> **The data server is the product; clients are consumers of the data server.**

Rosalind is therefore not primarily a collection of import scripts or an AI application. It is a reliable personal-data substrate that preserves source evidence, builds a provider-independent canonical model, and exposes that model to software and AI agents.

---

# 2. Core Architectural Principles

## 2.1 Canonical personal-data model

All provider-specific data is mapped into a common internal model.

For example:

```text
Google Contact ──┐
Apple Contact  ──┼──> Canonical Person
Meta Contact   ──┘
```

"Canonical" means the standard internal representation used by Rosalind, independent of the provider's original format.

The canonical model is not the raw source of truth. Raw provider data is retained separately.

The first version of the canonical people model does **not** distinguish between "me" and "other people."

All people are represented using the same `core.person` model.

The concept of "me" is an account-level relationship to a person and is therefore intentionally outside the person entity itself. This keeps the model suitable for future multi-user and person-sharing scenarios.

---

## 2.2 Raw data is immutable

Provider observations are preserved in the `raw` schema.

A raw source record represents an immutable observation of a provider object.

A new import containing a changed representation of the same provider object creates another raw record. An identical observation is deduplicated using `payload_sha256`.

This means:

```text
Provider object
      │
      ├── observation A
      ├── observation B
      └── observation C
```

can be preserved without overwriting historical evidence.

Raw records are never cascade-deleted because a canonical person or fact is deleted.

The raw layer is the audit trail from which canonical data can be rebuilt.

---

## 2.3 Provider formats are isolated

Provider-specific formats must never leak into the canonical model.

Use:

```text
Provider export/API response
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

The canonical model should not contain concepts whose only purpose is to accommodate one provider's representation.

Provider-specific metadata that is useful but has no canonical representation remains available through the raw source record and provenance layer.

---

## 2.4 Source identity is distinct from canonical identity

A provider's identifier is not the canonical identity of an entity.

For example:

```text
Google / people/c123
Apple  / ABC123
```

may both refer to:

```text
Person / 123
```

Therefore:

```text
provider identifier
       ↓
source_identity
       ↓
canonical person
```

`core.source_identity` represents the identity of an object within a specific external source account.

`core.person` represents Rosalind's canonical entity.

This distinction allows entity-resolution logic to improve without modifying historical source data.

---

## 2.5 Provenance is first-class

Canonical facts must remain traceable to the source evidence that supports them.

For example:

```text
Person
  │
  └── canonical email
        │
        ├── Google assertion
        ├── Gmail assertion
        └── shared-profile assertion
```

A canonical fact may have multiple independent assertions supporting it.

Source-level metadata such as:

* primary status
* verification status
* source timestamps
* source-specific metadata

belongs to the assertion, not to the canonical fact.

Canonical decisions such as:

* which email is primary
* which name is primary
* which birthday is canonical

belong to the canonical fact tables.

This deliberately separates:

> "What did the provider say?"

from:

> "What does Rosalind currently believe?"

---

## 2.6 Client independence

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
            ┌───────────┼───────────┐
            ▼           ▼           ▼
           CLI      AI agent     Browser/App
```

The backend must not depend on the CLI's implementation.

---

# 3. Initial Technology Choices

## Backend

**Python**

Reasons:

* Excellent data-processing ecosystem
* Strong JSON/Pydantic support
* Excellent AI/LLM ecosystem
* Good HTTP/API tooling
* Fast development
* Suitable for I/O-heavy ingestion workloads
* Easy to introduce optimized components later if required

The backend should remain a single application initially rather than being split into microservices.

### Proposed Python stack

| Concern                         | Technology        |
| ------------------------------- | ----------------- |
| Python/runtime                  | Python 3.14+      |
| Environment and dependencies    | `uv`              |
| API                             | FastAPI           |
| Validation / API schemas        | Pydantic v2       |
| Configuration                   | pydantic-settings |
| Database abstraction            | SQLAlchemy 2      |
| PostgreSQL driver               | psycopg 3         |
| Database migrations             | Alembic           |
| HTTP client                     | httpx             |
| Testing                         | pytest            |
| Property-based testing          | Hypothesis        |
| Integration-test infrastructure | Testcontainers    |
| Formatting / linting            | Ruff              |
| Static type checking            | mypy              |
| Structured logging              | structlog         |

The backend should keep clear boundaries between:

```text
API schemas        → Pydantic
Domain objects     → Python classes / dataclasses
Persistence models → SQLAlchemy
Configuration      → pydantic-settings
```

Pydantic should primarily be used at system boundaries and for validation rather than becoming the representation of every internal object.

---

## Environment management

Use `uv` for:

* Python version management
* Virtual environments
* Dependency installation
* Dependency locking

The repository should contain:

```text
pyproject.toml
uv.lock
```

Development and CI environments should be reproducible from the lock file.

Do not introduce Conda unless a future requirement makes it necessary.

---

## Quality gates

Rosalind should use a layered quality-gate system covering code quality, testing, security, containers, scripts, and database integrity.

The baseline Python checks are:

```text
format
lint
typecheck
tests
```

Additional checks should cover security and the other artifacts in the repository.

### Python security

Use:

* **Bandit** — static analysis for common Python security issues
* **pip-audit** — vulnerability scanning of Python dependencies

These should run locally and in CI.

### Secret scanning

Use **Gitleaks** to detect accidentally committed secrets such as:

* API keys
* OAuth credentials
* database credentials
* tokens
* private keys

Secret scanning should be authoritative in CI and may also run locally.

### Docker

Dockerfiles should be linted with **Hadolint**.

Built container images should be scanned with **Trivy** for vulnerabilities and relevant configuration/security issues.

```text
Dockerfile
    ↓
Hadolint

Docker image
    ↓
Trivy
```

### Shell scripts

If the repository contains shell scripts, they should be checked with:

* **ShellCheck** — correctness and common shell pitfalls
* **shfmt** — shell script formatting

### CLI client

The CLI is a separate client project and should have its own quality gates.

If implemented in Python, its baseline checks should include:

```text
Ruff format
Ruff lint
mypy
pytest
Bandit
pip-audit
```

Typer, if used, belongs to the CLI project and is not a backend dependency.

### Database and migrations

CI should verify that the database schema can be created and migrated successfully from an empty PostgreSQL database.

At minimum:

```text
empty PostgreSQL
    ↓
alembic upgrade head
    ↓
integration tests
```

Use `alembic check` to detect unexpected schema drift.

### Data/import quality

Provider fixture tests and import tests should verify domain-specific invariants in addition to schema validation.

Examples:

```text
provider IDs are unique
required fields are present
dates are valid
normalization is idempotent
re-importing identical data creates no duplicates
```

Import health checks should also detect suspicious changes in record counts or structure.

---

## Developer task runner

Use **`just`** as the project task runner for common development commands.

Example:

```makefile
check:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy .
    uv run pytest

test:
    uv run pytest

lint:
    uv run ruff check .
    uv run ruff format --check .

typecheck:
    uv run mypy .

format:
    uv run ruff format .

serve:
    uv run uvicorn rosalind.api.app:app --reload

ci: lint typecheck test
```

Typical local usage:

```bash
just check
just test
just format
just serve
```

`just` is developer tooling and is not part of the Rosalind backend runtime.

---

## Local Git hooks

Consider **pre-commit** for fast checks that should run automatically before a commit.

Pre-commit should primarily run quick formatting and linting checks. The complete test suite should not necessarily run on every commit if it becomes slow.

The authoritative full quality gate remains:

```bash
just check
```

and the same checks should run in CI.

---

## Testing strategy

Testing should be divided into several layers:

```text
tests/
├── unit/
├── integration/
├── api/
├── e2e/
└── fixtures/
```

### Unit tests

Test pure domain and transformation logic without external infrastructure:

* Provider parsing
* Normalization
* Canonicalization
* Entity resolution
* Hashing
* Deduplication
* Date/time handling

### Provider fixture tests

Maintain representative provider export fixtures and test that adapters continue to produce the expected source representation and canonical output.

These tests act as compatibility contracts for provider formats.

### Integration tests

Use a real PostgreSQL instance rather than extensively mocking database behavior.

Test:

```text
service
  ↓
SQLAlchemy
  ↓
PostgreSQL
```

Use Testcontainers or an equivalent containerized PostgreSQL environment for repeatable tests.

### API tests

Use pytest with httpx to exercise the FastAPI application without requiring a separately running HTTP server.

### End-to-end tests

Maintain a small number of tests covering the complete pipeline:

```text
provider fixture
    ↓
ingestion
    ↓
validation
    ↓
staging
    ↓
canonicalization
    ↓
PostgreSQL
    ↓
API
    ↓
expected result
```

### Property-based tests

Use Hypothesis selectively for important invariants, particularly where transformations must be stable or idempotent.

Examples:

```text
normalize(normalize(x)) == normalize(x)

re-importing identical data creates no duplicates

canonicalization preserves required information
```

---

## Background processing

Imports may become long-running operations. The initial architecture should therefore leave room for background jobs:

```text
API
 ↓
create import
 ↓
background processing
 ↓
parse → validate → stage → normalize → commit
```

Do not introduce Celery/Redis by default. Rosalind is initially a self-hosted personal-data system, so infrastructure should remain minimal. Add a dedicated job system only when the workload requires it.

Do not introduce Rust initially.

Rust can be considered later for measured bottlenecks such as:

* Very large-file parsing
* Hashing
* Compression
* Encryption
* CPU-intensive transformations
* Memory-intensive local processing

---

# 4. Database

## PostgreSQL

**PostgreSQL** is the primary datastore.

Use PostgreSQL for:

* Canonical relational data
* Source/import metadata
* Provenance
* Full-text search
* JSONB for provider-specific source data
* `pgvector` for semantic search when needed

Recommended database stack:

```text
SQLAlchemy 2
    ↓
psycopg 3
    ↓
PostgreSQL
```

Use Alembic for schema migrations.

Do not make a vector database the primary source of truth.

PostgreSQL is intentionally used as the common substrate for structured data, provenance, search, and eventually vector retrieval rather than introducing separate databases prematurely.

---

# 5. Clients

Clients are separate applications from the backend.

The backend must expose a client-independent API and must not contain CLI-specific presentation or interaction logic.

Initial architecture:

```text
┌──────────────────┐
│   Rosalind CLI   │
│   client         │
└────────┬─────────┘
         │ HTTP/API
         ▼
┌──────────────────┐
│ Rosalind Backend │
│                  │
│ FastAPI          │
│ Domain           │
│ Ingestion        │
│ Persistence      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   PostgreSQL     │
└──────────────────┘
```

The CLI is therefore **not part of the Python backend**.

The CLI should have its own project/package and communicate with Rosalind through the public API. It should not import backend internals or directly access the database.

Potential clients:

1. CLI — first client
2. AI-agent interface
3. Browser/web UI
4. Native desktop/mobile applications
5. Third-party applications

The same backend API should serve all of them.

### Client independence invariant

The backend should remain usable if the CLI is completely replaced.

```text
CLI ───────────────┐
                   │
AI agent ──────────┤
                   ▼
               Public API
                   ▲
Browser ───────────┤
                   │
Desktop app ───────┘
```

No backend functionality should depend on a particular client being present.

---

# 6. High-Level Architecture

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
                   Raw source records
                           │
                           ▼
                  Canonicalization /
                  entity resolution
                           │
                           ▼
                     Core data model
                           │
                 ┌─────────┼──────────┐
                 ▼         ▼          ▼
              REST/API  Search/AI  CLI client
                           │
                  ┌────────┼────────┐
                  ▼        ▼        ▼
              structured  FTS     vectors
              retrieval          when needed
```

---

# 7. Source / Import Layer

## 7.1 Source accounts

A source account represents an account at an external provider.

Examples:

```text
Google personal
Google work
Apple iCloud
Microsoft work
```

`public.source_account` remains the provider/account credential concept.

The canonical person model does not depend on a single provider account.

A source account may produce many source records and source identities.

---

## 7.2 Data imports

Every Takeout/export is an independent import.

Import metadata tracks:

* source account
* lifecycle
* parser and parser version
* file-level hashes
* import-level metadata
* observation timing

An identical provider object may be encountered by multiple imports. Reconciliation at the raw level is based on content identity, while canonicalization determines whether observations represent the same underlying entity.

---

## 7.3 Import upload flow

Raw provider files are stored in object storage before semantic parsing happens.

The CLI is responsible for the data plane; the backend owns the import lifecycle and is authoritative for import metadata.

```text
CLI ──1. POST /imports/google/takeout──────────────► API
  ▲                                                │ creates import
  │                                                │
  │◄───────────────────────────────────────────────┘
  │
  ├─ 2. walk directory
  ├─ 3. collect metadata + SHA-256
  ├─ 4. upload files ─────────────────────────────► object storage
  └─ 5. POST /imports/{id}/complete ─────────────► API
                                                   │
                                                   ▼
                                               PostgreSQL
```

Key properties:

* The CLI reads file bytes to hash and upload, but does **not** parse or interpret their contents.
* The backend derives storage keys and authoritative import statistics.
* Each import remains a distinct observation.
* Canonical reconciliation happens after raw data has been accepted.
* Original files remain in object storage independently from canonical entities.

---

# 8. Raw Source Records

The `raw` schema is the immutable evidence layer.

## 8.1 Design goals

The raw layer must:

* preserve provider data as received;
* retain historical observations;
* avoid provider-to-canonical information loss;
* allow canonicalization logic to be rerun;
* provide an audit trail;
* remain independent from downstream entity deletion.

The raw layer is deliberately source-oriented rather than domain-oriented.

---

## 8.2 `raw.source_record`

The first implementation uses one immutable row per distinct observed source payload.

Conceptually:

```sql
CREATE TABLE raw.source_record (
    id UUID PRIMARY KEY,

    source_account_id UUID NOT NULL
        REFERENCES public.source_account(id)
        ON DELETE RESTRICT,

    resource_type TEXT NOT NULL,
    external_id TEXT NOT NULL,

    source_etag TEXT,
    source_updated_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,

    payload JSONB NOT NULL,
    payload_sha256 TEXT NOT NULL,

    UNIQUE (
        source_account_id,
        resource_type,
        external_id,
        payload_sha256
    )
);
```

The combination:

```text
source_account
resource_type
external_id
```

identifies a source object within a provider account.

`payload_sha256` identifies the exact observed representation.

This means:

```text
same source object
+
same payload
=
same raw observation
```

An identical re-import therefore does not create another raw payload row.

The import itself may still be recorded separately at the import layer.

---

## 8.3 Why raw data is retained

Raw data is intentionally independent from the canonical model.

Suppose a future version of entity resolution changes how a Google Person is mapped:

```text
Old canonicalization
    Google Person → Person A

New canonicalization
    Google Person → Person B
```

The raw record should not need to change.

The raw layer allows the system to recompute canonical data from historical evidence.

It is therefore treated as an append-only evidence layer.

---

# 9. Canonical Person Model

The canonical people model is divided into:

```text
core.person
core.source_identity
core.source_assertion
```

plus attribute-specific fact tables.

The model intentionally distinguishes:

```text
Person
    = canonical real-world entity

Source identity
    = identity of that entity in an external source

Source assertion
    = a statement/evidence observed in a source record

Canonical fact
    = Rosalind's current resolved representation of that attribute
```

---

# 10. `core.person`

`core.person` is intentionally minimal:

```sql
CREATE TABLE core.person (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

The first version does **not** put fields such as `display_name`, `email`, `gender`, or `birth_date` directly on `person`.

Those values are represented as canonical facts in dedicated tables.

For example:

```text
Person
  │
  ├── names
  ├── emails
  ├── dates
  ├── genders
  └── locales
```

This avoids maintaining multiple competing representations of the same fact.

For example, there is no separate:

```text
person.display_name
```

that could disagree with:

```text
person_name.display_name
```

The attribute tables are therefore the canonical fact layer.

---

# 11. No `me` vs `other` person model

The initial model deliberately contains only one person type.

There is no:

```text
me_person
contact_person
```

and no:

```text
person.is_me
```

A person is simply:

```text
core.person
```

The fact that one person is the owner of a Rosalind account is an account-level relationship and will later be represented through an account's `self_person_id`.

Conceptually:

```text
account
   │
   └── self_person_id ──> person
```

while contacts are simply other rows in `core.person`.

This keeps the domain model symmetric and leaves room for future person sharing.

For example, the same logical model can later support:

```text
Alice's account
    └── self → Person A

Bob's account
    └── self → Person B
```

with both accounts independently storing and resolving people.

A shared profile can then be represented as another source of information about a person rather than as a different class of person.

---

# 12. `core.source_identity`

A source identity links a canonical person to an identity in a particular external source account.

```sql
CREATE TABLE core.source_identity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    person_id UUID NOT NULL
        REFERENCES core.person(id)
        ON DELETE CASCADE,

    source_account_id UUID NOT NULL
        REFERENCES public.source_account(id)
        ON DELETE RESTRICT,

    source_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    resource_name TEXT,

    UNIQUE (
        source_account_id,
        source_type,
        external_id
    )
);
```

The source account is part of the identity scope.

This is important because the same external identifier may have meaning only within a particular provider account.

For example:

```text
Google account A / PROFILE / 123
Google account B / PROFILE / 123
```

must not be assumed to be the same identity merely because `external_id` is equal.

`resource_name` is retained as provider-specific identity metadata, but it is not used as Rosalind's canonical primary key.

---

# 13. `core.source_assertion`

A source assertion records a specific statement observed in a raw source record.

```sql
CREATE TABLE core.source_assertion (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_record_id UUID NOT NULL
        REFERENCES raw.source_record(id)
        ON DELETE CASCADE,

    source_identity_id UUID
        REFERENCES core.source_identity(id)
        ON DELETE RESTRICT,

    field_path TEXT NOT NULL,

    source_primary BOOLEAN,
    source_verified BOOLEAN,

    metadata JSONB
);
```

An assertion may contain source-level metadata such as:

```text
source_primary
source_verified
provider-specific metadata
```

The assertion itself belongs to the raw observation.

Therefore:

```text
source_record
    ↓
source_assertion
```

is part of the evidence chain.

An assertion survives deletion of a canonical person or canonical fact.

It is removed only when its raw source record is removed.

The current schema uses:

```text
UNIQUE(source_record_id, field_path)
```

because a source assertion identifies a particular field location within a particular immutable source record.

The field path is a locator into that specific snapshot. It is not the canonical identity of the fact.

For example:

```text
source_record = R123
field_path    = $.names[0]
```

means:

> the value found at `$.names[0]` in raw snapshot `R123`.

---

# 14. Canonical Fact Tables

Canonical person attributes are represented as dedicated relational tables.

The first version includes:

```text
core.person_name
core.person_email
core.person_date
core.person_gender
core.person_locale
```

This allows each attribute to have its own:

* validation rules;
* normalization;
* uniqueness constraints;
* canonical primary-value semantics;
* provenance links.

---

## 14.1 Names

```sql
CREATE TABLE core.person_name (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    person_id UUID NOT NULL
        REFERENCES core.person(id)
        ON DELETE CASCADE,

    display_name TEXT,
    given_name TEXT,
    family_name TEXT,

    is_primary BOOLEAN NOT NULL DEFAULT false
);
```

Exactly one name may be canonical primary for a person:

```sql
CREATE UNIQUE INDEX person_name_one_primary
ON core.person_name (person_id)
WHERE is_primary;
```

Multiple names may coexist because different providers or source observations may contain legitimate variations.

---

## 14.2 Email addresses

```sql
CREATE TABLE core.person_email (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    person_id UUID NOT NULL
        REFERENCES core.person(id)
        ON DELETE CASCADE,

    email TEXT NOT NULL,
    email_normalized TEXT NOT NULL,

    type TEXT,

    is_primary BOOLEAN NOT NULL DEFAULT false,
    is_verified BOOLEAN NOT NULL DEFAULT false,

    UNIQUE (person_id, email_normalized)
);
```

The normalized email is used for matching and uniqueness.

The original representation is retained in `email`.

A normalized column is deliberately used instead of PostgreSQL's `citext` extension. This keeps normalization explicit and controlled by application/domain logic rather than making database comparison semantics implicitly responsible for it.

Indexes:

```sql
CREATE INDEX person_email_normalized_idx
ON core.person_email (email_normalized);
```

Exactly one email may be canonical primary:

```sql
CREATE UNIQUE INDEX person_email_one_primary
ON core.person_email (person_id)
WHERE is_primary;
```

`is_verified` represents Rosalind's current canonical verification status. Provider-specific verification evidence remains on `source_assertion`.

---

## 14.3 Dates

```sql
CREATE TABLE core.person_date (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    person_id UUID NOT NULL
        REFERENCES core.person(id)
        ON DELETE CASCADE,

    date_type TEXT NOT NULL DEFAULT 'birthday',

    year INTEGER,
    month INTEGER,
    day INTEGER,

    is_primary BOOLEAN NOT NULL DEFAULT false
);
```

Dates are represented using separate components rather than PostgreSQL's `date` type because some providers support partial dates.

For example:

```text
1991
1991-01
01-01
1991-01-01
```

The canonical model should preserve that precision.

Validation includes:

```text
month ∈ [1, 12]
day ∈ [1, 31]
day ⇒ month
```

Exactly one canonical primary date may exist for each person and date type:

```sql
CREATE UNIQUE INDEX person_date_one_primary
ON core.person_date (person_id, date_type)
WHERE is_primary;
```

The raw provider representation remains available in the raw source record.

---

## 14.4 Gender

```sql
CREATE TABLE core.person_gender (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    person_id UUID NOT NULL
        REFERENCES core.person(id)
        ON DELETE CASCADE,

    value TEXT NOT NULL,

    is_primary BOOLEAN NOT NULL DEFAULT false
);
```

Exactly one canonical gender value may be primary:

```sql
CREATE UNIQUE INDEX person_gender_one_primary
ON core.person_gender (person_id)
WHERE is_primary;
```

The value remains `TEXT` rather than a PostgreSQL enum so that the canonical model does not become tightly coupled to a fixed provider ontology.

---

## 14.5 Locale

```sql
CREATE TABLE core.person_locale (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    person_id UUID NOT NULL
        REFERENCES core.person(id)
        ON DELETE CASCADE,

    value TEXT NOT NULL,

    is_primary BOOLEAN NOT NULL DEFAULT false
);
```

Exactly one locale may be canonical primary:

```sql
CREATE UNIQUE INDEX person_locale_one_primary
ON core.person_locale (person_id)
WHERE is_primary;
```

Locale values are stored as locale identifiers such as:

```text
en-GB
fr-FR
```

rather than being decomposed into separate language and country columns.

---

# 15. Fact / Assertion Link Tables

Each canonical fact can be supported by one or more source assertions.

The relationship is:

```text
Canonical fact
      │
      ├── Assertion A
      ├── Assertion B
      └── Assertion C
```

The current implementation uses one link table per fact type:

```text
person_name_assertion
person_email_assertion
person_date_assertion
person_gender_assertion
person_locale_assertion
```

Conceptually:

```sql
CREATE TABLE core.person_email_assertion (
    assertion_id UUID PRIMARY KEY
        REFERENCES core.source_assertion(id)
        ON DELETE CASCADE,

    person_email_id UUID NOT NULL
        REFERENCES core.person_email(id)
        ON DELETE CASCADE
);

CREATE INDEX person_email_assertion_fact_idx
ON core.person_email_assertion (person_email_id);
```

The equivalent pattern is used for the other fact tables.

The important property is that one canonical fact can have multiple supporting observations.

For example:

```text
person_email
    alex@example.com
          │
          ├── Google ACCOUNT assertion
          ├── Google PROFILE assertion
          └── Gmail assertion
```

Canonical data therefore does not need to duplicate a value simply because several providers agree on it.

The current link-table design uses `assertion_id` as the primary key, which intentionally models one canonical-fact link per source assertion for these initial attribute types.

---

# 16. Source vs Canonical Primary Status

Provider-level `primary` metadata and Rosalind-level `is_primary` have different meanings.

For example, a provider may say:

```text
Email A
    source_primary = true
```

This means:

> The provider considers Email A primary in that source.

It does not necessarily mean:

> Rosalind should consider Email A canonical primary.

Therefore:

```text
source_assertion.source_primary
```

stores provider evidence, while:

```text
person_email.is_primary
```

stores Rosalind's resolved canonical choice.

This separation is essential when different providers disagree.

Example:

```text
Google:
    home@example.com → source_primary

Microsoft:
    work@example.com → source_primary

Rosalind:
    work@example.com → canonical primary
```

The original provider assertions remain unchanged.

---

# 17. Canonical Resolution

Canonicalization converts source assertions into canonical facts.

Conceptually:

```text
Raw source record
       ↓
Source assertion(s)
       ↓
Normalization
       ↓
Entity resolution
       ↓
Canonical fact
```

For each attribute, the canonicalization layer determines:

* whether the value is equivalent to an existing canonical fact;
* whether a new fact should be created;
* which fact is canonical primary;
* how multiple assertions should be linked;
* whether conflicting observations remain as separate facts.

Canonicalization must never mutate historical raw evidence.

---

# 18. Example: Google Person

Given a synthetic Google Person resource containing:

```text
resourceName = people/demo-123456789

names:
    Alex Morgan
    given = Alex
    family = Morgan

email:
    alex.morgan@example.com
    primary = true
    verified = true

birthday:
    1988-04-17

locale:
    en-GB
```

the pipeline is:

```text
Google Person JSON
        │
        ▼
raw.source_record
        │
        ├── $.names[0]
        ├── $.emailAddresses[0]
        ├── $.birthdays[0]
        └── $.locales[0]
        │
        ▼
core.source_assertion
        │
        ▼
canonicalization
        │
        ├── core.person
        ├── core.person_name
        ├── core.person_email
        ├── core.person_date
        └── core.person_locale
```

The canonical representation may then look conceptually like:

```text
Person
    id = P1

Name
    display_name = Alex Morgan
    given_name   = Alex
    family_name  = Morgan
    is_primary   = true

Email
    email            = alex.morgan@example.com
    email_normalized = alex.morgan@example.com
    is_primary       = true
    is_verified      = true

Date
    date_type = birthday
    year      = 1988
    month     = 4
    day       = 17
    is_primary = true

Locale
    value = en-GB
    is_primary = true
```

The canonical person has no dependency on the Google representation.

---

# 19. Deletion Semantics

The data model distinguishes two different forms of deletion.

## 19.1 Deleting canonical data

Deleting a person or fact can remove dependent canonical structures:

```text
person
  ↓ CASCADE
person_name
person_email
person_date
person_gender
person_locale
```

and:

```text
fact
  ↓ CASCADE
fact_assertion
```

This does **not** delete the raw source records.

Historical source evidence must remain available for auditability and rebuilding.

---

## 19.2 Deleting raw source data

Deleting a raw source record removes the assertions derived from it:

```text
raw.source_record
    ↓ CASCADE
core.source_assertion
    ↓ CASCADE
fact_assertion link
```

A canonical fact itself is not inherently a child of a single source assertion and therefore is not automatically deleted simply because one observation disappears.

Canonicalization/reconciliation logic must determine the resulting canonical state.

---

## 19.3 Source identity lifecycle

`core.source_identity` represents the mapping between a canonical person and an external source identity.

It is distinct from raw evidence.

The current FK configuration deliberately prevents accidental deletion of a source account that still has source identities or raw records.

The interaction between:

```text
source_identity.person_id → CASCADE
source_assertion.source_identity_id → RESTRICT
```

means deletion of a person may be blocked while retained assertions still reference source identities.

If person deletion is introduced as a supported operation, this FK behavior must be treated as an explicit lifecycle decision rather than an accidental database side effect.

---

# 20. Agent Read Model

The `agent` schema is a derived read model.

The storage model is optimized for:

* integrity
* normalization
* provenance
* reconciliation
* relational querying

The agent model is optimized for:

* compact responses
* predictable structure
* low context consumption
* semantic operations
* AI tool usage

The two should therefore not be identical.

---

# 21. `agent.person_profile`

The first agent-facing representation is a database view:

```sql
CREATE VIEW agent.person_profile AS
SELECT
    p.id AS person_id,
    n.display_name,
    n.given_name,
    n.family_name,
    e.email AS primary_email,
    e.is_verified AS email_verified,
    g.value AS gender,
    l.value AS locale,
    d.year AS birth_year,
    d.month AS birth_month,
    d.day AS birth_day
FROM core.person p

LEFT JOIN core.person_name n
    ON n.person_id = p.id
   AND n.is_primary = true

LEFT JOIN core.person_email e
    ON e.person_id = p.id
   AND e.is_primary = true

LEFT JOIN core.person_gender g
    ON g.person_id = p.id
   AND g.is_primary = true

LEFT JOIN core.person_locale l
    ON l.person_id = p.id
   AND l.is_primary = true

LEFT JOIN core.person_date d
    ON d.person_id = p.id
   AND d.date_type = 'birthday'
   AND d.is_primary = true;
```

The view intentionally exposes the current canonical values rather than raw provider metadata.

The result can be serialized for an agent as:

```json
{
  "person_id": "...",
  "display_name": "Alex Morgan",
  "given_name": "Alex",
  "family_name": "Morgan",
  "primary_email": "alex.morgan@example.com",
  "email_verified": true,
  "gender": "female",
  "locale": "en-GB",
  "birth_year": 1988,
  "birth_month": 4,
  "birth_day": 17
}
```

The agent should not need to understand the normalized relational representation underneath this view.

---

# 22. Agent-Oriented API

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

This abstraction also allows the storage schema to evolve without changing the agent-facing API.

---

# 23. Structured, Lexical, and Semantic Retrieval

Search should be implemented as several complementary capabilities rather than one universal mechanism.

## Structured retrieval

Use PostgreSQL relational indexes.

Examples:

```text
email address
provider ID
canonical person ID
event time
organization ID
```

## Lexical retrieval

Use PostgreSQL full-text search and/or trigram indexes.

Examples:

```text
"Alex Morgan"
"Alix Morgan"
```

## Semantic retrieval

Use embeddings when meaning rather than exact terms is the retrieval criterion.

Examples:

```text
"messages about moving to London"
"conversations about changing jobs"
```

The retrieval system should choose the appropriate mechanism rather than forcing every query through vector search.

---

# 24. Embeddings

When semantic retrieval is required, use `pgvector`.

Conceptually:

```sql
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

Potential embedded objects include:

* Email threads
* Individual emails
* Calendar events
* Documents
* Person summaries
* Other natural-language fragments

Do not embed every relational fact.

For example:

```text
birth_date
email
event.start_at
organization.name
```

should remain structured.

Natural-language content is the primary candidate for semantic indexing.

Embeddings are a derived representation and can always be regenerated.

---

# 25. AI-Derived Information

AI-derived information must remain separate from canonical facts.

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

* model
* generation timestamp
* source/dependency hash
* optionally prompt/version metadata

AI output is evidence or derived interpretation, not authoritative canonical data.

---

# 26. Context Projections

Do not return large normalized datasets to an AI agent when a compact projection is sufficient.

For example:

```json
{
  "person": {
    "id": "P123",
    "name": "Alex Morgan",
    "emails": [
      "alex.morgan@example.com",
      "alex@northstar.example"
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

# 27. Future Person Sharing

The common person model deliberately leaves room for future cross-user sharing.

The underlying abstraction is:

```text
Person
   │
   ├── canonical facts
   ├── source identities
   └── provenance
```

A user's account can later designate one of its persons as its owner:

```text
account
   │
   └── self_person_id → person
```

A limited shared representation can then be generated from that person's canonical data:

```text
Canonical Person
       │
       ▼
Shared Profile
       │
       ├── name
       ├── email
       ├── photo
       └── selected attributes
```

A receiving Rosalind instance should treat the received representation as another source of information rather than as a fundamentally different person type.

Conceptually:

```text
Alice's Rosalind
    Person A
       │
       ▼
  shared profile
       │
       ▼
Bob's Rosalind
       │
       ▼
source record
       │
       ▼
canonical person
```

This allows the receiving system to reconcile the shared data with information it already has from other sources.

The same person can therefore be:

```text
self
contact
friend
colleague
shared profile
```

depending on the account and relationship context, without requiring different person schemas.

---

# 28. Email Model

Email messages are separate from participants.

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

    thread_id UUID REFERENCES email_thread(id),

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
```

Participant records initially identify email addresses.

They may later resolve to canonical people.

This preserves the important distinction:

```text
raw participant identity
        ↓
email address
        ↓
resolved person
```

A message is not required to have a resolved person in order to be retained.

---

# 29. Calendar Model

## Calendar

```sql
CREATE TABLE calendar (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    source_account_id UUID
        REFERENCES public.source_account(id),

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

Event participants may initially identify only an email address and later be resolved to a canonical person.

This is intentional:

```text
Event participant
    ↓
email address
    ↓
optional Person resolution
```

A missing person resolution must never cause the underlying event or participant information to be discarded.

---

# 30. Temporal Data

Important data should preserve history rather than only current state.

Distinguish:

* event time / validity time
* source update time
* observation time
* database creation/update time

For example:

```text
employment
    €70k — Jan 2024 → Dec 2024
    €80k — Jan 2025 → present
```

The system should eventually support queries such as:

> "What did Rosalind know about this person at a particular point in time?"

The raw layer provides historical source observations.

The canonical layer can later introduce explicit validity intervals when the domain requires them.

---

# 31. Data Lineage

The system should make it possible to trace information through:

```text
Provider export/API response
    ↓
Raw source record
    ↓
Source assertion
    ↓
Canonical fact
    ↓
Agent/AI projection
```

For example:

```text
Alex Morgan
    │
    ├── email: alex.morgan@example.com
    │      │
    │      ├── Google contact assertion
    │      └── Gmail assertion
    │
    └── phone: +1-202-555-0147
           └── Apple contact assertion
```

This is essential for:

* Debugging
* Trust
* AI citations
* Reprocessing
* Entity-resolution improvements
* Explaining canonical decisions

A future agent-facing API should be able to expose provenance when the user needs to understand why a fact is believed.

---

# 32. Handling Conflicting Evidence

Different providers may disagree.

For example:

```text
Google:
    name = Alex Morgan

Microsoft:
    name = Alex Morgan

Other source:
    name = Alex M.
```

The raw observations remain separate.

The canonical model can represent multiple names:

```text
person_name
    Alex Morgan
    Alex M.
```

with one selected as canonical primary.

Similarly:

```text
Google:
    birthday = 1988-04-17

Other source:
    birthday = 1987-12-03
```

Both observations may remain as evidence.

Canonicalization determines whether one is primary, whether both should remain, or whether the conflict requires explicit handling.

The system should never destroy contradictory evidence merely to simplify the canonical representation.

---

# 33. Import State Machine

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

# 34. Provider Adapter Architecture

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

# 35. Intermediate Source Representation

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
    "given": "Alex",
    "family": "Morgan"
  },

  "emails": [
    {
      "address": "alex.morgan@example.com",
      "label": "home"
    }
  ]
}
```

Apple's representation of the same contact should produce the same source-level structure.

This makes the canonicalization layer provider-independent.

---

# 36. Validation and Schema Evolution

Use Pydantic models for provider-specific formats.

Important rule:

## Additive provider changes

If a provider adds a field:

```text
newField
```

do not necessarily fail the import.

Preserve unknown fields.

The raw record remains authoritative for the complete provider payload.

## Breaking provider changes

If a required field disappears or the structure fundamentally changes:

```text
validation → failure
```

Do not write corrupted canonical data.

Instead quarantine the import.

---

# 37. Import Health Checks

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

# 38. Golden Test Fixtures

Maintain representative synthetic provider fixtures:

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

Fixtures should use synthetic values rather than real personal data.

Test both:

1. Provider parsing
2. Expected canonical output

Provider fixtures are compatibility contracts for provider formats.

Canonical fixtures are contracts for Rosalind's normalization and canonicalization behavior.

---

# 39. Search Architecture

Search should be implemented as several complementary capabilities rather than one universal mechanism.

## Exact / structured search

Use PostgreSQL relational indexes.

Examples:

```text
email address
provider ID
canonical person ID
event time
organization ID
```

## Fuzzy / lexical search

Use PostgreSQL full-text search and/or trigram indexes.

Examples:

```text
"Alex Morgan"
"Alix Morgan"
```

## Semantic search

Use embeddings for natural-language content when exact matching is insufficient.

Examples:

```text
"messages about moving to London"
"conversations about changing jobs"
```

The retrieval system should choose the appropriate mechanism rather than forcing every query through vector search.

---

# 40. AI / Semantic Layer

AI functionality is a consumer of the canonical model, not the canonical model itself.

The architecture is:

```text
Canonical data
    │
    ├── structured retrieval
    ├── lexical retrieval
    ├── relationship traversal
    └── semantic retrieval
             │
             ▼
        Agent context
             │
             ▼
           AI model
```

AI-generated results should remain explicitly derived.

The agent must not silently write an interpretation back into a canonical field.

---

# 41. Non-Negotiable Invariants

The following should be treated as architectural invariants:

1. **Raw source records are immutable.**
2. **Raw evidence survives downstream canonical-entity deletion.**
3. **Canonical data is derived from source observations.**
4. **Re-importing identical data is idempotent.**
5. **Provider IDs are never used as canonical IDs.**
6. **Provider-specific formats never leak into the canonical model.**
7. **Source identity is distinct from canonical identity.**
8. **A canonical fact may have multiple supporting source assertions.**
9. **Provider `primary`/`verified` metadata is distinct from Rosalind's canonical decisions.**
10. **Provider schema changes cannot corrupt canonical data.**
11. **Failed imports are quarantined rather than partially committed.**
12. **Canonical entities maintain provenance.**
13. **AI-derived information never silently overwrites canonical facts.**
14. **The backend is independent of any client.**
15. **The canonical database should be rebuildable from retained source data.**
16. **The person model does not distinguish "me" from other people.**
17. **Agent-facing projections are derived from canonical data and are not sources of truth.**

---

# 42. Initial Project Scope

Start with three Google data domains:

```text
Google Takeout
    │
    ├── Contacts
    ├── Gmail
    └── Calendar
```

## Phase 1 — Infrastructure

* PostgreSQL
* SQLAlchemy
* psycopg
* Alembic
* FastAPI
* Backend configuration with pydantic-settings
* Import tracking
* Raw source storage
* Separate CLI client communicating through the API

## Phase 2 — Google Contacts

* Takeout parser
* Versioned parser
* Pydantic validation
* Raw source records
* Source identities
* Source assertions
* Canonical Person
* Names
* Emails
* Dates
* Gender
* Locale
* Entity resolution
* Provenance
* `agent.person_profile`

## Phase 3 — Gmail

* Messages
* Threads
* Participants
* Person resolution
* Incremental reconciliation

## Phase 4 — Calendar

* Calendars
* Events
* Participants
* Person resolution

## Phase 5 — Search

* PostgreSQL full-text search
* Fuzzy matching
* Cross-domain queries

## Phase 6 — AI

* Agent-oriented API
* Context projections
* AI summaries
* Embeddings
* Semantic search

## Phase 7 — Additional clients

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

# 43. Guiding Example

The architecture should ultimately make this possible:

```text
User:

"What is my relationship with Alex Morgan?"
```

The system should be able to combine:

```text
Person
    ↓
Source identities
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

The database does not need to know how the AI will reason about the answer.

It only needs to provide:

* reliable structured facts;
* historical source evidence;
* relationships;
* efficient retrieval;
* provenance.

The agent-facing layer is responsible for assembling those pieces into useful context.

---

# 44. Architectural Summary

Rosalind is organized around three progressively more semantic layers:

```text
RAW
"What did the source actually give us?"
        │
        ▼
CORE
"What does Rosalind currently believe?"
        │
        ▼
AGENT
"What representation is most useful to software and AI?"
```

The core people model itself is:

```text
Person
   │
   ├── canonical facts
   │      ├── names
   │      ├── emails
   │      ├── dates
   │      ├── genders
   │      └── locales
   │
   ├── source identities
   │
   └── provenance
          └── source assertions
```

This gives Rosalind a stable foundation for ingesting heterogeneous sources while preserving the ability to improve normalization, entity resolution, search, and AI capabilities independently.

The goal is therefore not simply to build a database of personal data.

The goal is to build a **reliable personal-data substrate that both traditional software and AI agents can query and reason over.**

---

# 45. Canonical Backend Stack

The initial Rosalind backend stack is intentionally small:

```text
Python 3.14+
│
├── uv                    environment / dependencies
│
├── FastAPI               HTTP API
├── Pydantic v2           validation / API schemas
├── pydantic-settings     configuration
│
├── SQLAlchemy 2          database abstraction
├── psycopg 3             PostgreSQL driver
├── Alembic               migrations
│
├── httpx                 HTTP client
│
├── pytest                testing
├── Hypothesis            property-based testing
├── Testcontainers        integration-test infrastructure
│
├── Ruff                  formatting / linting
├── mypy                  static typing
├── just                  developer task runner
├── pre-commit            optional local Git hooks
├── Bandit                Python security linting
├── pip-audit              Python dependency vulnerability scanning
├── Gitleaks              secret scanning
├── Hadolint              Dockerfile linting
├── Trivy                 container/image security scanning
├── ShellCheck            shell script linting
├── shfmt                 shell script formatting
└── structlog             structured logging
```

The CLI is a separate client project. If implemented in Python, it may use Typer, but Typer is **not a backend dependency**.

The architectural priority is to keep implementation choices replaceable while preserving the core Rosalind contracts:

```text
canonical data model
+
provider adapters
+
source identity
+
provenance
+
idempotent ingestion
+
client-independent API
```

---

# Sources

## Personal knowledge graphs

[Martin G. Skjæveland, Krisztian Balog, Nolwenn Bernard, Weronika Łajewska, Trond Linjordet, *An ecosystem for personal knowledge graphs: A survey and research roadmap*, AI Open, 27 Feb 2024](https://www.sciencedirect.com/science/article/pii/S2666651024000044)

## Google

[Google Support, How to download your Google data](https://support.google.com/accounts/answer/3024190?hl=en)

[Google Support, Share a copy of your data with a third party](https://support.google.com/accounts/answer/14452558?hl=en&ref_topic=7188671)

[Google Developers, REST Resource: people](https://developers.google.com/people/api/rest/v1/people)

[Google Developers, Develop on Google Workspace](https://developers.google.com/workspace/guides/get-started)

## PostgreSQL

[PostgreSQL Documentation — JSON Types](https://www.postgresql.org/docs/current/datatype-json.html)

[PostgreSQL Documentation — Full Text Search](https://www.postgresql.org/docs/current/textsearch.html)

[PostgreSQL Documentation — `pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html)

[PostgreSQL Documentation — Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)

## Provenance

[W3C, PROV-O: The PROV Ontology](https://www.w3.org/TR/prov-o/)

## Vector search

[pgvector](https://github.com/pgvector/pgvector)

## Agent interface

[Model Context Protocol — Tools](https://modelcontextprotocol.io/specification/)
