# Rosalind CLI

Command-line client for the Rosalind personal-data warehouse.

The CLI talks to the Rosalind backend over HTTP and uploads source files
directly to object storage (S3-compatible). It does not access the database
directly.

## Setup

```bash
uv sync
```

## Run

```bash
uv run rosalind --help
uv run rosalind status
uv run rosalind import create google ~/Downloads/Takeout
uv run rosalind import list
uv run rosalind import show <import_id>
uv run rosalind import delete <import_id>
uv run rosalind google connect
uv run rosalind google import profile
uv run rosalind google disconnect
```

## Configuration

| Variable                  | Default                  | Description                     |
|---------------------------|--------------------------|---------------------------------|
| `ROSALIND_API_URL`        | `http://localhost:8000`  | Base URL of the backend         |
| `ROSALIND_S3_ENDPOINT`    | `http://localhost:8333`  | S3-compatible endpoint (SeaweedFS) |
| `ROSALIND_S3_ACCESS_KEY`  | `rosalind`               | S3 access key                   |
| `ROSALIND_S3_SECRET_KEY`  | `rosalind`               | S3 secret key                   |
| `ROSALIND_S3_BUCKET`      | `rosalind`               | Fallback bucket (backend is authoritative) |
| `ROSALIND_S3_REGION`      | `us-east-1`              | S3 region                       |

Example:

```bash
ROSALIND_API_URL=http://some-server:8000 uv run rosalind status
```
