# Rosalind Backend

FastAPI backend for the Rosalind personal-data warehouse.

## Setup

```bash
uv sync
```

## Run

```bash
just migrate
just serve
# or
uv run uvicorn rosalind.adapters.inbound.http.app:app --reload
```

The API is served at `http://localhost:8000`.

## Policy service

The policy engine is a separate deployable in the same package. It shares
PostgreSQL but owns the `authz`, `semantic` and `audit` schemas and has its own
Alembic chain. It never imports the RAG/search stack.

```bash
just policy-migrate   # alembic -c alembic-policy.ini upgrade head
just policy-serve     # uv run rosalind-policy (default 127.0.0.1:8001)
```

Run it on the host (not in a container) during development so it can reach a
local Ollama endpoint at `127.0.0.1:11434`. The model allowlist lives under
`policy.models` in `rosalind.yaml` (see `rosalind.yaml.example`).

## Configuration

Configuration is read from environment variables (prefix `ROSALIND_`):

| Variable                | Default                                                              |
|-------------------------|----------------------------------------------------------------------|
| `ROSALIND_DATABASE_URL` | `postgresql+psycopg://rosalind:rosalind@localhost:5432/rosalind`      |
| `ROSALIND_S3_BUCKET`    | `rosalind`                                                           |
| `ROSALIND_S3_ENDPOINT`  | `http://localhost:8333`                                              |
| `ROSALIND_S3_ACCESS_KEY`| `rosalind`                                                           |
| `ROSALIND_S3_SECRET_KEY`| `rosalind`                                                           |
| `ROSALIND_S3_REGION`    | `us-east-1`                                                          |

## Database migrations

```bash
just migrate           # alembic upgrade head
just revision "msg"    # autogenerate a new migration
```

## Endpoints

| Method | Path                        | Description                                    |
|--------|-----------------------------|------------------------------------------------|
| GET    | `/health`                   | Process liveness check → `{"status": "ok"}`   |
| POST   | `/imports`                  | Create an import (`via=file` or `via=api`)      |
| POST   | `/imports/{id}/complete`    | Submit the manifest and finalize an import     |
| GET    | `/imports`                  | List all imports                               |
| GET    | `/imports/{id}`             | Fetch an import and its files                  |
| DELETE | `/imports/{id}`             | Delete an import and its raw objects           |
| POST   | `/auth/google/connect`      | Start a Google OAuth authorization             |
| GET    | `/auth/google/status`       | Check an authorization request status          |
| DELETE | `/auth/google`              | Revoke and remove stored Google credentials    |
