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

## Connect Google

Rosalind can import data from Google using the People API. The backend owns the
OAuth flow; the CLI only drives it.

### 1. Create Google OAuth credentials

1. Open the [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
2. Create an **OAuth client ID** of type **Web application**.
3. Add an authorized redirect URI matching `ROSALIND_GOOGLE_REDIRECT_URI`
   (default `http://localhost:8000/auth/google/callback`).
4. Copy the client ID and secret into your environment (`.env`):

```bash
ROSALIND_GOOGLE_CLIENT_ID=<your-client-id>
ROSALIND_GOOGLE_CLIENT_SECRET=<your-client-secret>
```

### 2. Generate a token-encryption key

OAuth tokens are stored encrypted at rest using a Fernet key:

```bash
uv run --directory backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set it as `ROSALIND_TOKEN_ENCRYPTION_KEY`.

### 3. Connect and import

```bash
cd cli
uv run rosalind google connect          # opens a browser, stores credentials
uv run rosalind google import profile   # fetches your People API profile
```

The Google authorization flow requests offline access so the backend can
refresh the access token without further interaction.

