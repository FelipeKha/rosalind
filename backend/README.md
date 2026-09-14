# Rosalind Backend

FastAPI backend for the Rosalind personal-data warehouse.

## Setup

```bash
uv sync
```

## Run

```bash
just serve
# or
uv run uvicorn rosalind.api.app:app --reload
```

The API is served at `http://localhost:8000`.

## Endpoints

| Method | Path      | Description                            |
|--------|-----------|----------------------------------------|
| GET    | `/health` | Process liveness check → `{"status": "ok"}` |
