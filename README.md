# rosalind

Rosalind is a self-hosted personal-data warehouse. The backend exposes a
client-independent API; the CLI is a client of that API.

## Prerequisites

- [uv](https://docs.astral.sh/uv/)
- [Docker](https://www.docker.com/) (for PostgreSQL, SeaweedFS, and integration tests)
- [just](https://github.com/casey/just) (task runner)

## Start the local infrastructure

```bash
cp .env.example .env    # optional; defaults match the compose file
just up                 # starts PostgreSQL + SeaweedFS
```

This starts:

| Service    | Address             |
|------------|---------------------|
| PostgreSQL | `localhost:5432`    |
| SeaweedFS  | `localhost:8333` (S3 API) |

## Run the backend

```bash
just migrate            # apply database migrations (once)
just backend-serve      # starts uvicorn at http://localhost:8000
```

Or bring everything up in one command:

```bash
just dev                # up + migrate + serve
```

## Run the CLI client

In another terminal:

```bash
cd cli
uv sync                 # once, if deps are not installed yet
uv run rosalind --help
uv run rosalind status
uv run rosalind import google ~/Downloads/Takeout
```

The CLI reads `ROSALIND_API_URL` (default `http://localhost:8000`) and the S3
settings from the environment (see `.env.example`).
