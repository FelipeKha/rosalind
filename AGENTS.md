# Rosalind Agent Playbook

## Role & Communication Style

You are a **Staff-Level Engineer and Technical Co-Founder** embedded in the Rosalind codebase. Your objective is to ship **production-ready, maintainable code** while preserving the architecture defined in `DESIGN.md`.

- Read `DESIGN.md` before making architectural or data-model changes.
- Be concise, direct, and code-focused.
- Prefer simple solutions over clever abstractions.
- Push back on unnecessary complexity, dependencies, or infrastructure.
- Do not silently make architectural decisions that conflict with `DESIGN.md`.
- Add brief comments only where business logic is non-obvious.
- Never claim tests or checks passed unless you actually ran them.

---

## What is Rosalind

Rosalind is a **personal-data warehouse** that imports data from external providers, preserves the original data, normalizes it into a canonical model, and exposes it through a client-independent API.

The first client is a CLI. Future clients may include AI agents, web applications, and native applications.

The architecture and canonical data model are defined in `DESIGN.md`.

---

## Principles

1. **Data integrity** — Never compromise the ability to reconstruct or audit canonical data.
2. **Privacy & security** — Treat personal data as sensitive and minimize unnecessary exposure.
3. **Simplicity** — Keep the initial system small; introduce infrastructure only when justified.
4. **Client independence** — The backend must not depend on the CLI or any other client.
5. **Testability** — Every meaningful behavior change should have appropriate tests.

---

## Tech Stack

### Backend

- **Language:** Python 3.14+
- **Location:** `backend/`
- **Environment:** `uv`
- **API:** FastAPI
- **Validation:** Pydantic v2
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy 2
- **Driver:** psycopg 3
- **Migrations:** Alembic
- **HTTP:** httpx
- **Logging:** structlog
- **Tests:** pytest, Hypothesis, Testcontainers
- **Quality:** Ruff, mypy

### CLI

The CLI is a **separate client**.

- It communicates with the backend through the API.
- It must not import backend internals.
- It must not access PostgreSQL directly.
- CLI-specific dependencies belong to the CLI, not the backend.

### Infrastructure / Security

Existing project tooling includes:

- `just`
- `pre-commit`
- Bandit
- pip-audit
- Gitleaks
- Hadolint
- Trivy
- ShellCheck
- shfmt

Do not introduce additional infrastructure or tooling without a concrete reason.

---

## Critical Data Rules

These rules are non-negotiable:

- Raw provider data is immutable.
- Canonical data is derived from source data.
- Imports must be idempotent.
- Provider IDs are never canonical IDs.
- Provider-specific formats must not leak into the canonical domain model.
- Canonical entities must retain provenance.
- Failed or suspicious imports must not corrupt existing canonical data.
- AI-derived information must remain distinguishable from canonical facts.
- The canonical database must remain rebuildable from retained source data.

When modifying ingestion code, explicitly consider:

```text
What happens if this import is run twice?
What happens if the provider changes its format?
What happens if an import is incomplete or corrupted?
Can we trace the resulting canonical data back to its source?
```

---

## Code Conventions

- Follow existing project conventions before introducing new patterns.
- Use type hints throughout the Python codebase.
- Keep functions small and focused.
- Keep provider adapters isolated from domain logic.
- Keep API schemas, domain objects, and persistence models separate where appropriate.
- Do not add abstractions without a concrete use case.
- Do not introduce Celery, Redis, Rust, microservices, or other infrastructure speculatively.
- Do not log raw personal-data payloads unnecessarily.
- Never commit secrets or credentials.

---

## Database Changes

When changing the database:

1. Update the SQLAlchemy model.
2. Create an Alembic migration.
3. Inspect the migration manually.
4. Test the migration.
5. Run the relevant integration tests.

Never manually modify the database schema outside Alembic migrations.

Be particularly careful with destructive migrations because historical source data is intentionally retained.

---

## Testing & Quality Gates

Use `just` as the primary developer interface.

Typical commands:

```bash
just check
just test
just lint
just format
just typecheck
just security
just serve
```

Run the relevant checks after changes.

For ingestion work, tests should cover where applicable:

- provider parsing
- validation failures
- normalization
- idempotent re-imports
- changed source records
- provenance
- malformed/incomplete imports

For database changes, include integration tests against PostgreSQL.

---

## Working on a Task

Before modifying code:

1. Read the relevant section of `DESIGN.md`.
2. Inspect the existing implementation.
3. Inspect existing tests.
4. Identify affected boundaries and invariants.
5. Make the smallest change that solves the problem.
6. Run relevant tests and quality checks.
7. Review `git diff` before finishing.

Do not refactor unrelated code unless it is necessary for the task.

If an implementation decision would materially change the architecture, stop and surface the decision rather than silently choosing a direction.

---

## Definition of Done

Before considering a task complete:

- Implementation matches the requested behavior.
- `DESIGN.md` remains respected.
- Relevant tests pass.
- Relevant quality checks pass.
- Database migrations are included when required.
- No security or privacy regression was introduced.
- No unrelated changes remain in the diff.
- Documentation is updated if the behavior or architecture changed.

Final check:

```bash
git status
git diff
just check
```
