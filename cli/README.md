# Rosalind CLI

Command-line client for the Rosalind personal-data warehouse.

The CLI talks to the Rosalind backend over HTTP and uploads source files
directly to object storage (S3-compatible). It does not access the database
directly.

## Installation

```bash
uv sync
```

## rosalind

The Rosalind command-line client.

```
rosalind [command] [flags]
```

### Global options

`--json`

Emit machine-readable JSON instead of human-readable output.

`--profile <name>`

Load the config profile `<config_dir>/<name>.yaml` on top of the base config
(equivalent to setting `ROSALIND_PROFILE`). Profiles keep separate backends and
credentials, e.g. `--profile eval`.

### Commands

- [rosalind status](#rosalind-status)
- [rosalind auth](#rosalind-auth)
- [rosalind source](#rosalind-source)
- [rosalind import](#rosalind-import)
- [rosalind process](#rosalind-process)
- [rosalind index](#rosalind-index)
- [rosalind query](#rosalind-query)
- [rosalind search](#rosalind-search)

### Exit codes

`0` — success
`1` — operational failure
`2` — invalid usage

## rosalind status

Show whether the Rosalind backend is reachable.

```
rosalind status [flags]
```

### Examples

```bash
# Check that the backend is healthy
$ rosalind status
Backend: healthy
```

### See also

- [rosalind](#rosalind)

## rosalind auth

Authenticate with the Rosalind identity provider (Keycloak).

```
rosalind auth [command]
```

### Available commands

- [rosalind auth sign-in](#rosalind-auth-sign-in)
- [rosalind auth sign-up](#rosalind-auth-sign-up)
- [rosalind auth sign-out](#rosalind-auth-sign-out)
- [rosalind auth whoami](#rosalind-auth-whoami)

### See also

- [rosalind](#rosalind)

## rosalind auth sign-in

Sign in to Rosalind using the device authorization flow.

```
rosalind auth sign-in [flags]
```

### Options

`--browser` / `--no-browser`

Open the authorization URL in a browser.

### Examples

```bash
$ rosalind auth sign-in
Visit this URL to authorize Rosalind:
https://localhost:8080/realms/rosalind/device?user_code=ABCD-EFGH
Enter code: ABCD-EFGH
Signed in.
```

### See also

- [rosalind auth](#rosalind-auth)

## rosalind auth sign-up

Create a Rosalind account and sign in. Same device flow as `sign-in`; the
Keycloak page offers registration.

```
rosalind auth sign-up [flags]
```

### See also

- [rosalind auth](#rosalind-auth)

## rosalind auth sign-out

Sign out of Rosalind, clearing locally stored tokens and revoking them at the
identity provider (best effort).

```
rosalind auth sign-out [flags]
```

### See also

- [rosalind auth](#rosalind-auth)

## rosalind auth whoami

Show the currently authenticated Rosalind account (id, email, name).

```
rosalind auth whoami [flags]
```

### Examples

```bash
$ rosalind auth whoami
Account: 3fa85f64-5717-4562-b3fc-2c963f66afa6
Email:   jane@example.com
Name:    Jane Doe
```

### See also

- [rosalind auth](#rosalind-auth)

## rosalind source

Manage connected data providers.

```
rosalind source [command]
```

### Available commands

- [rosalind source create](#rosalind-source-create)
- [rosalind source connect](#rosalind-source-connect)
- [rosalind source disconnect](#rosalind-source-disconnect)
- [rosalind source list](#rosalind-source-list)
- [rosalind source show](#rosalind-source-show)

### See also

- [rosalind](#rosalind)

## rosalind source create

Declare a source without connecting it (for example, for Takeout imports).

```
rosalind source create <provider> --name <name> [flags]
```

### Options

`--name <string>` (required)

Source name (slug).

### Examples

```bash
# Declare a Google source for later Takeout imports
$ rosalind source create google --name google
```

### See also

- [rosalind source](#rosalind-source)

## rosalind source connect

Authorize Rosalind to access a provider account.

```
rosalind source connect <provider> [--name <name>] [flags]
```

### Options

`--name <string>`

Source name (slug). Defaults to the provider name.

`--browser` / `--no-browser`

Open the authorization URL in a browser.

### Examples

```bash
# Connect a Google account (opens a browser)
$ rosalind source connect google

# Connect with an explicit source name, without opening a browser
$ rosalind source connect google --name google --no-browser
```

### See also

- [rosalind source](#rosalind-source)

## rosalind source disconnect

Revoke access for a source. Imported data is retained.

```
rosalind source disconnect <source> [flags]
```

### Arguments

`<source>`

Source name (slug) or id.

### Examples

```bash
$ rosalind source disconnect google
Disconnected. Historical imports and data were retained.
```

### See also

- [rosalind source](#rosalind-source)

## rosalind source list

List connected and available sources.

```
rosalind source list [flags]
```

### Examples

```bash
$ rosalind source list
NAME      PROVIDER  STATUS       DISPLAY NAME
google    google    connected    Jane Doe
```

### See also

- [rosalind source](#rosalind-source)

## rosalind source show

Show details for a source.

```
rosalind source show <source> [flags]
```

### Arguments

`<source>`

Source name (slug) or id.

### Examples

```bash
$ rosalind source show google
Name:      google
Provider:  google
Status:    connected
```

### See also

- [rosalind source](#rosalind-source)

## rosalind import

Bring source data into Rosalind.

```
rosalind import [command]
```

### Available commands

- [rosalind import create](#rosalind-import-create)
- [rosalind import list](#rosalind-import-list)
- [rosalind import show](#rosalind-import-show)
- [rosalind import delete](#rosalind-import-delete)

### See also

- [rosalind](#rosalind)

## rosalind import create

Create an import from a source.

```
rosalind import create [--source <google|none>] [--via <file|api>] [<path>]
```

### Options

`--source <google|none>` (default: `none`)

Where the data comes from. `google` uses an existing connected source; `none`
uses a built-in local source for file-based imports.

`--via <file|api>` (default: `file`)

How the data enters Rosalind. `file` uploads a local file or folder; `api`
pulls all contacts directly from a connected provider (requires
`--source google`).

### Arguments

`<path>`

A file or folder to upload. Required for `--via file`, and not accepted for
`--via api`. The import format is inferred from each file's extension.

### Examples

```bash
# Import a local Google Takeout export (a folder)
$ rosalind import create --source google ~/Downloads/Takeout

# Import a single mbox archive
$ rosalind import create ~/Downloads/rosalind_synthetic_emails.mbox

# Import all contacts directly from the Google People API
$ rosalind import create --source google --via api
```

### See also

- [rosalind import](#rosalind-import)

## rosalind import list

List all imports.

```
rosalind import list [flags]
```

### Examples

```bash
$ rosalind import list
ID   SOURCE  VIA    INGESTION   PROCESSING  FILES  SIZE
42   google  file   completed   pending     1842   4.8 GB
```

### See also

- [rosalind import](#rosalind-import)

## rosalind import show

Inspect an import and its files.

```
rosalind import show <import-id> [flags]
```

### Arguments

`<import-id>`

Import id.

### See also

- [rosalind import](#rosalind-import)

## rosalind import delete

Delete an import and its raw files.

```
rosalind import delete <import-id> [flags]
```

### Options

`-y`, `--yes`

Skip the confirmation prompt.

### Arguments

`<import-id>`

Import id.

### Examples

```bash
$ rosalind import delete 42 --yes
Import 42 deleted.
```

### See also

- [rosalind import](#rosalind-import)

## rosalind process

Turn imported data into canonical data.

```
rosalind process [command]
```

### Available commands

- [rosalind process run](#rosalind-process-run)

### See also

- [rosalind](#rosalind)

## rosalind process run

Process an import into canonical data.

```
rosalind process run <import-id> [flags]
```

### Arguments

`<import-id>`

Import id.

### Examples

```bash
$ rosalind process run 42
Processing import completed
```

### See also

- [rosalind process](#rosalind-process)

## rosalind index

Build the searchable index for an import: split raw archives, canonicalize,
enrich, chunk, and embed. Running it twice is idempotent.

```
rosalind index <import-id> [--stage <stage>]
```

### Options

`--stage <string>`

Run a single stage (`split`, `canonicalize`, `reconcile`, `enrich`,
`attachments`, `chunk`, `embed`) instead of all of them.

`--self-email <string>`

Email address to treat as yours when computing message direction. When
indexing an mbox archive, `rosalind index` prompts for it (defaulting to the
signed-in account's email). In a non-interactive run (piped input, no TTY, or
`--json`), pass this flag explicitly.

### Arguments

`<import-id>`

Import id.

### Examples

```bash
# Build the full index for an import
$ rosalind index 42
Email address to treat as yours [me@example.com]:
Index complete
  Processed: 1842 messages
  Created:   1842
  Reused:    0
  Failed:    0

# Rebuild only the embeddings
$ rosalind index 42 --stage embed

# Non-interactive mbox import
$ rosalind index 42 --self-email me@example.com
```

### See also

- [rosalind import](#rosalind-import)

## rosalind query

Query canonical data.

```
rosalind query [command]
```

### Available commands

- [rosalind query people](#rosalind-query-people)
- [rosalind query person](#rosalind-query-person)

### See also

- [rosalind](#rosalind)

## rosalind query people

List known people, optionally filtered by a search query.

```
rosalind query people [--search <query>] [flags]
```

### Options

`--search <string>`

Search by name or email.

### Examples

```bash
# List all known people
$ rosalind query people

# Search for a specific person
$ rosalind query people --search "Alex"
```

### See also

- [rosalind query](#rosalind-query)

## rosalind query person

Show one person by id.

```
rosalind query person <person-id> [flags]
```

### Arguments

`<person-id>`

Person id.

### See also

- [rosalind query](#rosalind-query)

## rosalind search

Search indexed email. The query is natural language; `--keywords` adds exact
terms. Results are ranked, and `--cursor` pages through them.

```
rosalind search [query] [flags]
```

### Options

`--keywords <string>`, `-k <string>`

Exact-match terms for keyword search (names, amounts). Supports quoted phrases.

`--sender <string>`, `-s <string>`

Sender address or entity id. Repeat for more than one (OR).

`--since <date>`

Inclusive lower date bound (`YYYY-MM-DD`).

`--before <date>`

Exclusive upper date bound (`YYYY-MM-DD`).

`--has-attachment` / `--no-attachment`

Restrict to messages with (or without) attachments.

`--mode <hybrid|lexical|semantic>` (default: `hybrid`)

Retrieval mode.

`--limit <int>`, `-n <int>` (default: `10`)

Maximum number of results (1–25).

`--cursor <string>`

Opaque pagination cursor from a previous search.

### Arguments

`query`

Natural-language query. Optional when filters are given.

### Examples

```bash
# Natural-language search
$ rosalind search "roofer invoice"

# Exact terms, scoped to a sender and a date range
$ rosalind search --keywords '"market report"' --sender boss@example.com --since 2024-01-01

# Only messages with attachments
$ rosalind search "contract" --has-attachment

# Page through results
$ rosalind search "invoice" --limit 25 --cursor <token>
```

### See also

- [rosalind index](#rosalind-index)
- [rosalind query](#rosalind-query)

## Configuration

The CLI reads settings from environment variables and an optional YAML file.
Precedence, highest first:

1. Environment variables (`ROSALIND_*`)
2. The selected profile file `<config_dir>/<profile>.yaml`
3. The base file (`ROSALIND_CONFIG`, or `<config_dir>/rosalind.yaml`)
4. Built-in defaults

`config_dir` is `ROSALIND_CONFIG_DIR` (default `~/.config/rosalind`). Profiles
are selected with `--profile <name>` or `ROSALIND_PROFILE`; a missing base file
is ignored, but a missing profile file is an error. Stored credentials follow
the profile (`<config_dir>/<profile>/credentials.json`, or
`<config_dir>/credentials.json` for the default config).

Config files are optional: the built-in defaults already target the local
dev/eval endpoints. Use one only to point at another deployment:

```yaml
# ~/.config/rosalind/rosalind.yaml
api_url: https://rosalind.example.com
s3_endpoint: https://rosalind.example.com:8333
keycloak_url: https://auth.example.com
```

### Environment variables

| Variable                  | Default                  | Description                     |
|---------------------------|--------------------------|---------------------------------|
| `ROSALIND_CONFIG`         | `<config_dir>/rosalind.yaml` | Base config file path       |
| `ROSALIND_CONFIG_DIR`     | `~/.config/rosalind`     | Config and credentials directory |
| `ROSALIND_PROFILE`        | (none)                   | Profile layered over the base config |
| `ROSALIND_API_URL`        | `http://localhost:8000`  | Base URL of the backend         |
| `ROSALIND_SEARCH_TIMEOUT` | `60.0`                   | `rosalind search` request timeout, in seconds |
| `ROSALIND_S3_ENDPOINT`    | `http://localhost:8333`  | S3-compatible endpoint (SeaweedFS) |
| `ROSALIND_S3_ACCESS_KEY`  | `rosalind`               | S3 access key                   |
| `ROSALIND_S3_SECRET_KEY`  | `rosalind`               | S3 secret key                   |
| `ROSALIND_S3_BUCKET`      | `rosalind`               | Fallback bucket (backend is authoritative) |
| `ROSALIND_S3_REGION`      | `us-east-1`              | S3 region                       |
| `ROSALIND_KEYCLOAK_URL`   | `http://localhost:8080`  | Keycloak base URL               |
| `ROSALIND_KEYCLOAK_REALM` | `rosalind`               | Keycloak realm                  |
| `ROSALIND_KEYCLOAK_CLIENT_ID` | `rosalind-cli`       | Keycloak public client id       |

Example:

```bash
ROSALIND_API_URL=http://some-server:8000 uv run rosalind status
```
