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

### Commands

- [rosalind status](#rosalind-status)
- [rosalind source](#rosalind-source)
- [rosalind import](#rosalind-import)
- [rosalind process](#rosalind-process)
- [rosalind query](#rosalind-query)

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
rosalind import create --source <name> --type <takeout|api> [<path>] [flags]
```

### Options

`--source <string>` (required)

Source name (slug).

`--type <string>` (required)

Import type: `takeout` (a local provider export) or `api` (fetch directly from
a connected provider).

### Arguments

`<path>`

Path to a provider export. Required for `--type takeout`.

### Examples

```bash
# Import a local Google Takeout export
$ rosalind import create --source google --type takeout ~/Downloads/Takeout

# Import directly from the Google People API
$ rosalind import create --source google --type api
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
ID   SOURCE  TYPE      INGESTION   PROCESSING  FILES  SIZE
42   google  takeout   completed   pending     1842   4.8 GB
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
