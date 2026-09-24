# Rosalind — Design

**Project:** Rosalind

This document is the stable overview of Rosalind's architecture: what it is,
why it's shaped the way it is, and where to look for detail. It should
survive most refactors. Implementation detail that changes often — exact
schema DDL, provider-specific pipelines, MCP tool contracts — lives in the
companion docs linked from each section, not here.

```text
DESIGN.md                    ← you are here: vision, principles, shape
docs/schema.md                ← full canonical/raw schema reference
docs/mcp.md                   ← MCP server design and tool contracts
docs/providers/<name>.md      ← per-provider parsing pipelines
docs/invariants.md            ← the full non-negotiable invariants checklist
docs/roadmap.md               ← phased build plan
```

---

## 1. Vision

Rosalind is a self-hosted personal data warehouse. It ingests personal data
from providers (Google, Apple, Meta, Microsoft, …), normalizes it into a
stable canonical model, and exposes that model through a client-independent
API.

> **The data server is the product; clients are consumers of the data server.**

Clients — CLI (first), AI agents, browser/web UI, native apps, third-party
integrations — all sit on top of the same backend. Rosalind is not a
collection of import scripts or an AI application; it's a reliable
personal-data substrate that preserves source evidence, builds a
provider-independent canonical model, and exposes it to software and AI
agents alike.

---

## 2. Architecture at a Glance

Two layerings apply at once: a **data pipeline** (how information flows from
provider to agent) and a **code layering** (hexagonal / ports & adapters,
how the backend is structured internally).

### 2.1 Data pipeline

```text
External providers (Google, Apple, Meta, …)
        │
        ▼
Raw source records            "What did the source actually give us?"
        │  (immutable evidence)
        ▼
Provider validation / parsing / canonicalization
        │
        ▼
Core canonical model           "What does Rosalind currently believe?"
        │
        ▼
Agent / API read models        "What's most useful to software and AI?"
        │
   ┌────┼─────┐
   ▼    ▼     ▼
 REST  MCP  Search (FTS / vector)
```

The key failure-domain boundary: **raw persistence happens before provider
validation or canonicalization.** A provider format change or a parsing bug
must never cause the original payload to be discarded — see [§8](#8-raw-layer).

### 2.2 Code layering (hexagonal)

```text
adapters ──► application ──► domain
```

* **`domain`** — canonical model, observations, pure business rules. No
  framework or infrastructure imports.
* **`application`** — use cases, canonicalization, and **ports** (Protocols
  describing what the domain needs from the outside world, e.g.
  `PersonRepository`). Never imports concrete adapter classes.
* **`adapters`** — concrete implementations of ports, split into `inbound`
  (HTTP/FastAPI, MCP, CLI-facing endpoints — things that drive the
  application) and `outbound` (SQLAlchemy/Postgres, object storage, provider
  HTTP clients — things the application drives). The composition root
  (`main`/app factory) is the only place concrete adapters are wired to
  ports.

```text
backend/src/rosalind/
├── domain/            entities, observations, value objects
├── application/
│   ├── services/       use cases (PersonService, ingestion, canonicalization)
│   └── ports/           Protocols (repositories, storage, etc.)
└── adapters/
    ├── inbound/         http/, mcp/, ingestion/ (parsers driven by imports)
    └── outbound/        persistence/ (SQLAlchemy), storage/, provider clients
```

This layering is what makes the client-independence and provider-isolation
principles below enforceable in code, not just in prose: REST and MCP are
both inbound adapters calling the same application services; every provider
adapter and every persistence detail is swappable behind a port.

---

## 3. Core Principles

These are the invariant *shapes* of the system. Each links to more detail
where useful.

1. **Canonical model, independent of providers.** All provider data is
   mapped into one internal model (`core.person`, …). The canonical model
   never contains concepts that exist only to accommodate one provider's
   format. See [§7](#7-canonical-model).

2. **Raw data is immutable evidence.** Every accepted provider payload is
   stored as-is in `raw.source_record` before any parsing happens, and is
   never cascade-deleted when canonical data is deleted. It's the audit
   trail the canonical model can always be rebuilt from. See
   [§8](#8-raw-layer).

3. **Source identity ≠ canonical identity.** A provider's ID
   (`people/c123`) is not Rosalind's identity for that entity.
   `core.source_identity` bridges the two, scoped to a source account, so
   entity-resolution logic can improve without touching historical data.

4. **Provenance is first-class.** Every canonical fact traces back to the
   source assertion(s) that support it. "What did the provider say?" and
   "what does Rosalind currently believe?" are deliberately different
   questions with different tables.

5. **Client independence.** The backend exposes a client-agnostic API/domain
   layer. No backend functionality may depend on a particular client (CLI,
   browser, agent) being present; the CLI in particular must not import
   backend internals or touch the database directly.

6. **Domain has no infrastructure dependencies.** Enforced by the hexagonal
   layering in [§2.2](#22-code-layering-hexagonal): `domain` and
   `application` never import SQLAlchemy, FastAPI, or provider SDKs
   directly — only through ports.

7. **AI-derived data is evidence, not truth.** Summaries, embeddings, and
   agent output are recorded as derived interpretations and must never
   silently overwrite a canonical fact.

The full, exhaustive list of invariants (including narrower ones like "MCP
search results are bounded") lives in [`docs/invariants.md`](docs/invariants.md).

---

## 4. Technology Stack

```text
Python 3.14+ · uv (env/deps) · FastAPI · Pydantic v2 · pydantic-settings
SQLAlchemy 2 · psycopg 3 · Alembic · httpx
pytest · Hypothesis · Testcontainers
Ruff · mypy · just · pre-commit
Bandit · pip-audit · Gitleaks · Hadolint · Trivy · ShellCheck · shfmt
structlog
```

The backend is a single application (no microservices) for now. The CLI is
a separate client project (may use Typer) and is not a backend dependency.
Rust and Celery/Redis are deliberately deferred until a measured bottleneck
or workload requires them.

Boundaries between representations are kept explicit:

```text
API schemas          → Pydantic (system boundaries / validation only)
Domain objects        → dataclasses / plain Python
Application services  → use cases (application/services)
Ports                 → Protocols (application/ports)
Persistence models     → SQLAlchemy (adapters/outbound)
```

Per-tool rationale (why Python, why Postgres over a vector DB, etc.), if it
needs to be written down at all, belongs in an ADR rather than here — this
table is the durable part, the reasoning tends to be self-evident in
hindsight or stops mattering once the choice is load-bearing.

---

## 5. Quality & Testing

Baseline gate: `format → lint → typecheck → tests` via `just check`, the
same command locally and in CI. Layered test suite:

```text
tests/unit          domain & transformation logic, no infra
tests/integration    real Postgres (Testcontainers)
tests/api            FastAPI via httpx, no running server
tests/e2e            provider fixture → ingestion → API → result
tests/fixtures       synthetic provider exports (never real personal data)
```

Security/supply-chain checks (Bandit, pip-audit, Gitleaks, Hadolint, Trivy,
ShellCheck/shfmt) run locally and are authoritative in CI. Database
migrations are checked against an empty Postgres (`alembic upgrade head` +
`alembic check`) on every CI run.

Provider fixtures are compatibility contracts for provider formats; property-based tests (Hypothesis) cover key invariants such as
`normalize(normalize(x)) == normalize(x)` and re-import idempotency.

---

## 6. Layers

### 6.1 Raw layer

`raw.source_record` — one immutable row per distinct observed payload,
keyed by `(source_account, resource_type, external_id, payload_sha256)`.
Never cascade-deleted by canonical deletion. Goals: preserve provider data
as received, retain historical observations, allow canonicalization to be
rerun from evidence. Full schema: [`docs/schema.md`](docs/schema.md#raw).

### 6.2 Canonical (core) layer

```text
core.person              minimal — no display_name/email/etc. on the entity
core.source_identity      person ↔ external identity, scoped to source account
core.source_assertion     a statement observed in one raw record
core.person_name / _email / _date / _gender / _locale   canonical fact tables
person_*_assertion        link tables: one fact ↔ many supporting assertions
```

Each fact table has its own normalization, an `is_primary` uniqueness
constraint, and a value-uniqueness constraint so re-imports don't create
duplicate facts. `core.person` deliberately has **no `me` vs `other`
distinction** — "self" is an account-level `self_person_id` relationship,
kept outside the person entity to leave room for future person-sharing
between accounts. Full schema and the worked Google-Person example:
[`docs/schema.md`](docs/schema.md#core).

### 6.3 Agent layer

`agent.person_profile` and friends are **derived read models** — database
views (for now) optimized for compact, predictable, low-context responses,
not for integrity or normalization. They are not sources of truth. See
[§8](#8-agent-oriented-api) and [`docs/schema.md`](docs/schema.md#agent).

---

## 7. Canonical Model

*(See [`docs/schema.md`](docs/schema.md) for full DDL, indexes, and the
worked Google Person example.)*

The model is deliberately layered:

```text
Person            = canonical real-world entity
Source identity   = that entity's identity within one external source
Source assertion  = a statement observed in one raw source record
Canonical fact    = Rosalind's current resolved representation of an attribute
```

Provider-level `primary`/`verified` metadata belongs to the assertion
(`source_primary`, `source_verified`); Rosalind's own resolved choice
(`is_primary`) belongs to the fact table. These can disagree, and that's
expected — canonicalization decides, but never rewrites provider evidence.

Deletion semantics differ by layer: deleting canonical data cascades to
dependent canonical facts but never to raw evidence; deleting a raw record
cascades to its assertions but not automatically to canonical facts that
happen to no longer have supporting evidence (that's a reconciliation
decision). Source-account deletion is restricted while source identities or
raw records still reference it.

---

## 8. Ingestion Pipeline

```text
provider payload
     │
     ▼  (deterministic, canonical JSON + SHA-256)
raw.source_record  (upsert, ON CONFLICT DO NOTHING)
     │
     ▼
Provider-specific validation (Pydantic, extra="allow")
     │
     ▼
Provider-to-observation mapping (pure, no DB access, no normalization)
     │
     ▼
Canonicalization (resolve/create identity, person, facts, assertions)
     │
     ▼
core.*
```

State machine: `RECEIVED → SCANNING → RAW_PERSISTENCE → PARSING/VALIDATION →
SOURCE_MAPPING → NORMALIZING → ENTITY_RESOLUTION → COMMITTING → COMMITTED`,
with a `QUARANTINED/ERROR` branch after `RAW_PERSISTENCE` that never
discards the payload.

Provider adapters (`adapters/inbound/ingestion/<provider>/`) are
independently versioned, deterministic, and side-effect free — they map a
validated provider payload to frozen observation dataclasses and do nothing
else. Canonicalization and normalization (e.g. email lowercasing) live
outside the parser, in `application/services`.

The currently implemented pipeline (Google People `Person` →
`core.person`) is documented in detail in
[`docs/providers/google-person.md`](docs/providers/google-person.md).

Import health checks compare each import's record counts against prior
imports and quarantine suspicious deltas rather than silently replacing
good data.

---

## 9. Clients & API Boundary

```text
                 Rosalind Backend (API / application layer)
                        │
            ┌───────────┼───────────┬─────────────┐
            ▼           ▼           ▼             ▼
           CLI      AI agent    Browser/App   Other apps
```

The backend must remain usable if the CLI is replaced entirely; nothing in
`application` or `domain` may depend on a specific client. The CLI owns the
data plane for imports (reads bytes, hashes, uploads to object storage) but
never parses or interprets provider content — the backend is authoritative
for import lifecycle and statistics.

---

## 10. Agent-Oriented API

Do not expose SQL to AI agents. Expose semantic operations instead:
`find_person`, `get_person`, `search_personal_data`,
`find_people_related_to`, etc. REST and MCP are both thin inbound adapters
over the same `application` services — neither contains direct SQL.

**MCP** (Model Context Protocol) is the current AI-facing adapter:
stdio transport, strictly read-only in the MVP (`search_people`,
`get_person`), bounded results (max 25), explicit Pydantic response schemas
(never `dataclasses.asdict`), protocol stdout kept clean of logs. Full
design, deferred write-tool plan, and testing strategy:
[`docs/mcp.md`](docs/mcp.md).

Retrieval is split by mechanism rather than forced through one index:
**structured** (relational indexes — email, provider ID, event time),
**lexical** (Postgres FTS / trigram), **semantic** (pgvector embeddings, for
natural-language content only — structured facts like `birth_date` are
never embedded). AI-derived data (summaries, classifications) is stored
separately from canonical facts, tagged with model/timestamp/source-hash,
and never silently overwrites a canonical value.

---

## 11. Roadmap

```text
Phase 1  Infrastructure     Postgres, SQLAlchemy, Alembic, FastAPI, CLI skeleton
Phase 2  Google Contacts    full raw→canonical pipeline, agent.person_profile
Phase 3  Gmail              messages, threads, participant resolution
Phase 4  Calendar           calendars, events, participant resolution
Phase 5  Search             FTS, fuzzy matching, cross-domain queries
Phase 6  AI                 agent API, context projections, embeddings
Phase 7  Additional clients browser, desktop/mobile
```

Detail and current status: [`docs/roadmap.md`](docs/roadmap.md).

---

## 12. Open Questions / Deliberately Deferred

* Person deletion as a supported operation (FK/lifecycle implications are
  known but not yet designed — see `docs/schema.md`).
* MCP write tools (`create_person`, `update_person`, …) — deferred until
  the Actor/auth model exists.
* `get_my_profile` / account-level `self_person_id` — deferred; MCP
  currently operates on canonical people only.
* Explicit temporal validity intervals on canonical facts (e.g. employment
  history) — the raw layer already preserves history; canonical validity
  ranges are a later addition.
* Remote MCP transport, authN/authZ.
* Full provenance graph exposed via MCP responses (currently deferred;
  underlying data is already provenance-linked).

---

## References

See [`docs/references.md`](docs/references.md) for the full bibliography
(personal knowledge graphs, provenance/PROV-O, MCP spec, pgvector, Postgres
docs).
