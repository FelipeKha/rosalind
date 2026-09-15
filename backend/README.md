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
uv run uvicorn rosalind.api.app:app --reload
```

The API is served at `http://localhost:8000`.

## Configuration

Configuration is read from environment variables (prefix `ROSALIND_`):

| Variable                | Default                                                              |
|-------------------------|----------------------------------------------------------------------|
| `ROSALIND_DATABASE_URL` | `postgresql+psycopg://rosalind:rosalind@localhost:5432/rosalind`      |
| `ROSALIND_S3_BUCKET`    | `rosalind`                                                           |

## Database migrations

```bash
just migrate           # alembic upgrade head
just revision "msg"    # autogenerate a new migration
```

## Endpoints

| Method | Path                        | Description                                    |
|--------|-----------------------------|------------------------------------------------|
| GET    | `/health`                   | Process liveness check → `{"status": "ok"}`   |
| POST   | `/imports/google/takeout`   | Create a Google Takeout import                 |
| POST   | `/imports/{id}/complete`    | Submit the manifest and finalize an import     |
| GET    | `/imports/{id}`             | Fetch an import and its files                  |
