# rosalind

Rosalind is a self-hosted personal-data warehouse. The backend exposes a
client-independent API; the CLI is a client of that API.

## Run the backend

```bash
cd backend
uv sync                   # once, if deps are not installed yet
just serve                # starts uvicorn at http://localhost:8000
```

## Run the CLI client

In another terminal:

```bash
cd cli
uv sync                   # once, if deps are not installed yet
uv run rosalind --help
uv run rosalind status    # -> "Backend: healthy"
```

The CLI reads `ROSALIND_API_URL` (default `http://localhost:8000`):

```bash
ROSALIND_API_URL=http://some-server:8000 uv run rosalind status
```
