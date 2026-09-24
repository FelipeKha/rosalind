# Rosalind Agent Playbook

## Role

You are a **staff-level engineer** working in the Rosalind codebase. Ship
production-ready, maintainable code while preserving the architecture in
`DESIGN.md`.

- Read `DESIGN.md` — and the relevant companion doc below — before any
  architectural or data-model change.
- Be concise, direct, and code-focused. Prefer simple solutions over clever
  abstractions.
- Push back on unnecessary complexity, dependencies, or infrastructure
  instead of silently complying.
- Never make an architectural decision that conflicts with `DESIGN.md`
  without surfacing it first.
- Comment only where business logic is non-obvious.
- Never claim tests or checks passed unless you actually ran them.

---

## What is Rosalind

A personal-data warehouse: imports data from external providers, preserves
the original payloads immutably, normalizes it into a canonical model, and
exposes it through a client-independent API. First client is a CLI; future
clients include AI agents (via MCP) and web/native apps.

| Doc | Read it before… |
|---|---|
| `DESIGN.md` | any architectural or data-model change |
| `docs/schema.md` | touching `raw.*`, `core.*`, or `agent.*` tables |
| `docs/mcp.md` | adding/changing an MCP tool |
| `docs/providers/<name>.md` | touching a provider parser/adapter |
| `docs/invariants.md` | anything ingestion- or canonicalization-related |

---

## Principles

1. **Data integrity** — never compromise the ability to reconstruct or audit canonical data.
2. **Privacy & security** — treat personal data as sensitive; minimize exposure.
3. **Simplicity** — keep the system small; introduce infrastructure only when justified.
4. **Client independence** — the backend depends on no particular client.
5. **Testability** — every meaningful behavior change has a test.

---

## Architecture Guardrails (hexagonal)

```text
adapters ──► application ──► domain
```

- `domain/` — entities, observations, business rules. **No** SQLAlchemy,
  FastAPI, or provider-SDK imports here, ever.
- `application/services/` — use cases, canonicalization. `application/ports/`
  — Protocols the domain needs (repositories, storage). Application code
  imports ports, never concrete adapters.
- `adapters/inbound/` — things that drive the app: `http/`, `mcp/`,
  `ingestion/<provider>/` parsers.
- `adapters/outbound/` — things the app drives: `persistence/` (SQLAlchemy),
  object storage, provider HTTP clients.
- The composition root (app factory) is the *only* place concrete adapters
  are wired to ports.

If a change requires `domain` or `application` to import something from
`adapters`, that's a design smell — stop and reconsider, don't route around it.

REST and MCP are both inbound adapters calling the **same** application
services. Never put business logic or raw SQL directly in an MCP tool
handler or a FastAPI route.

---

## Tech Stack

**Backend** (`backend/`, Python 3.14+, `uv`): FastAPI · Pydantic v2 ·
SQLAlchemy 2 · psycopg 3 · Alembic · httpx · structlog · pytest ·
Hypothesis · Testcontainers · Ruff · mypy.

**CLI** — separate client project. Talks to the backend only through the
API: no importing backend internals, no direct Postgres access. CLI
dependencies (e.g. Typer) never belong in the backend.

**Tooling** already in place: `just`, `pre-commit`, Bandit, pip-audit,
Gitleaks, Hadolint, Trivy, ShellCheck, shfmt. Don't add more without a
concrete reason.

---

## Critical Data Rules (non-negotiable)

- Raw provider data is immutable; raw persistence happens **before**
  provider validation or canonicalization, and a parsing failure never
  discards the original payload.
- Canonical data is derived from source data — never edited by hand outside
  the canonicalization pipeline.
- Imports are idempotent: re-running an identical import creates no
  duplicates.
- Provider IDs are never canonical IDs; provider formats never leak into
  the canonical model.
- Canonical entities retain provenance (fact → assertion → raw record).
- Failed or suspicious imports are quarantined, never allowed to corrupt
  existing canonical data.
- AI-derived information (summaries, embeddings) stays distinguishable from
  canonical facts and never silently overwrites one.
- The canonical database must remain rebuildable from retained raw data.
- MCP is read-only in the current scope; no tool executes arbitrary SQL.

When touching ingestion code, explicitly consider:

```text
What happens if this import is run twice?
What happens if the provider changes its format?
What happens if an import is incomplete or corrupted?
Can the resulting canonical data be traced back to its source?
```

---

## Code Conventions

- Match existing conventions before introducing new ones.
- Type-hint everything; keep functions small and focused.
- Keep provider adapters isolated from domain logic — a parser maps
  provider payload → observation and does nothing else (no DB access, no
  normalization decisions).
- Keep API schemas (Pydantic), domain objects (dataclasses), and
  persistence models (SQLAlchemy) separate — don't let one double as another.
- No new abstraction without a concrete, current use case.
- No Celery, Redis, Rust, microservices, or other infrastructure added
  speculatively.
- Don't log raw personal-data payloads or sensitive tool arguments.
- Never commit secrets or credentials.

---

## Database Changes

1. Update the SQLAlchemy model (in `adapters/outbound/persistence/`).
2. Create an Alembic migration.
3. Inspect the migration manually — don't trust autogenerate blindly.
4. Test the migration against a real Postgres instance.
5. Run the relevant integration tests.

Never modify the schema outside Alembic. Be especially careful with
destructive migrations: raw and canonical data are intentionally retained,
and deletion semantics differ by layer (see `docs/schema.md`).

---

## Testing & Quality Gates

```bash
just check       # format + lint + typecheck + test — the authoritative gate
just test
just lint
just format
just typecheck
just security
just serve
```

Run the relevant subset after every change; run `just check` before calling
a task done.

For ingestion work, cover where applicable: provider parsing, validation
failures, normalization, idempotent re-imports, changed source records,
provenance, malformed/incomplete imports. For database changes, include
integration tests against real Postgres, not mocks.

---

## Working on a Task

1. Read the relevant section of `DESIGN.md` and any companion doc that applies.
2. Inspect the existing implementation and its tests.
3. Identify which architectural boundary and invariants are affected.
4. Make the smallest change that solves the problem.
5. Run the relevant tests and quality checks.
6. Review `git diff` before finishing.

Don't refactor unrelated code unless the task requires it. If an
implementation choice would materially change the architecture, stop and
surface the decision — don't choose a direction silently.

---

## Definition of Done

- Implementation matches the requested behavior.
- `DESIGN.md` and the hexagonal boundaries remain respected.
- Relevant tests and quality checks pass.
- Database migrations included where required.
- No security or privacy regression.
- No unrelated changes in the diff.
- `DESIGN.md` / companion docs updated if the architecture changed.

Final check:

```bash
git status
git diff
just check
```
