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

When you run recipes through `just`, the root `.env` file is loaded into the
environment (see `set dotenv-load` in the `justfile`). This feeds both
`docker compose` and the backend/CLI processes, so values such as
`ROSALIND_DATABASE_URL`, the S3 settings, and the Google OAuth credentials are
picked up automatically. Already-exported shell variables take precedence.

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
just dev                # up + install embedding deps + migrate + serve
```

## Local embeddings (BGE-M3)

By default the backend embeds in-process via [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding)
on Apple's MPS GPU — no separate serving container. This needs the optional
`ml` dependency group (PyTorch + FlagEmbedding):

```bash
just backend-install-ml   # one-time (also done by `just dev`)
uv run --directory backend python -c \
  "import torch; print('MPS:', torch.backends.mps.is_available())"
```

The first embedding run downloads the `BAAI/bge-m3` weights (~2.2 GB) to the
Hugging Face cache. Configuration knobs (all `ROSALIND_`-prefixed):

| Setting | Default | Meaning |
|---------|---------|---------|
| `ROSALIND_EMBEDDER_BACKEND` | `flagembedding` | `flagembedding` (in-process) or `tei` (remote server via `ROSALIND_EMBEDDER_URL`) |
| `ROSALIND_EMBEDDER_DEVICE` | `auto` | `auto` (MPS if available), `mps`, or `cpu` |
| `ROSALIND_EMBEDDER_USE_FP16` | `false` | FP32 baseline; set `true` for FP16 |
| `ROSALIND_EMBEDDER_BATCH_SIZE` | `8` | Inference batch size |
| `ROSALIND_EMBEDDER_MAX_LENGTH` | `512` | Max token length (chunks are capped at 480) |

## Reranking (bge-reranker-v2-m3)

Reranking is opt-in: set `ROSALIND_SEARCH_RERANKER=bge-reranker-v2-m3/v1` to
enable the cross-encoder reorder step. It runs in-process via FlagEmbedding on
MPS by default (the same `ml` group as above), and downloads `BAAI/bge-reranker-v2-m3`
(~1.1 GB) on first use.

| Setting | Default | Meaning |
|---------|---------|---------|
| `ROSALIND_SEARCH_RERANKER` | *(unset)* | Version stamp that enables reranking (e.g. `bge-reranker-v2-m3/v1`) |
| `ROSALIND_SEARCH_RERANKER_BACKEND` | `flagembedding` | `flagembedding` (in-process) or `tei` (remote server via `ROSALIND_SEARCH_RERANKER_URL`) |
| `ROSALIND_SEARCH_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | Model id for the in-process backend |
| `ROSALIND_SEARCH_RERANKER_DEVICE` | `auto` | `auto` (MPS if available), `mps`, or `cpu` |
| `ROSALIND_SEARCH_RERANKER_USE_FP16` | `false` | FP32 baseline; set `true` for FP16 |

## Run the CLI client

In another terminal:

```bash
cd cli
uv sync                 # once, if deps are not installed yet
uv run rosalind --help
uv run rosalind status
uv run rosalind source create google --name google
uv run rosalind import create --source google ~/Downloads/Takeout
uv run rosalind import list
uv run rosalind process run <import-id>
uv run rosalind query people
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
uv run rosalind source connect google        # opens a browser, stores credentials
uv run rosalind import create --source google --type api
uv run rosalind source disconnect google   # revokes access, keeps imported data
```

The Google authorization flow requests offline access so the backend can
refresh the access token without further interaction.





Launch backend:
`just dev`                  # launch backend
`just cli-tool-install`     # install rosalind-cli

Create eval run:
Sign in:
`rosalind auth sign-in`

Create import:
`rosalind import create e2e/fixtures/google/takeout/Mail/rosalind_synthetic_emails.mbox`

Index import:
`rosalind index 80eddc3e-0154-4b5b-913d-9470a18ffff8`

