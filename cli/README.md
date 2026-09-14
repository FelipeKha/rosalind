# Rosalind CLI

Command-line client for the Rosalind personal-data warehouse.

The CLI talks to the Rosalind backend over HTTP. It does not access the
database directly.

## Setup

```bash
uv sync
```

## Run

```bash
uv run rosalind --help
uv run rosalind status
```

## Configuration

| Variable          | Default                  | Description            |
|-------------------|--------------------------|------------------------|
| `ROSALIND_API_URL`| `http://localhost:8000`  | Base URL of the backend |

Example:

```bash
ROSALIND_API_URL=http://some-server:8000 rosalind status
```
