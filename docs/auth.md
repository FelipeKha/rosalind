# Authentication

Rosalind delegates identity to **Keycloak** (OIDC / OAuth 2.1) and only ever
validates bearer tokens — it never issues credentials, stores passwords, or
renders login UI. The REST API and the MCP server validate the same way, using
the same token verifier.

> **Authentication is not authorization.** This document covers *who is
> calling*. Rosalind does not yet scope data per account — see
> [Authorization status](#authorization-status).

## Account model

```text
Keycloak JWT (iss, sub) ──► AccountIdentity (issuer, subject) ──► Account
```

Two tables, deliberately separate concerns:

| Table | Schema | Purpose |
|---|---|---|
| `account` | public | Rosalind's own notion of a user: `id`, `self_person_id` (nullable FK → `core.person`), timestamps. |
| `account_identity` | public | A login from an identity provider: `issuer`, `subject`, unique on `(issuer, subject)`, `last_seen_at`. |

`account` is a Rosalind concept; `account_identity` is an identity-provider
concept. This split leaves room for multiple IdPs and multiple identities per
account without leaking provider concepts into `account`.

`account` is **not** `public.source_account`. A source account is a *provider
data* account (e.g. "Google personal") that Rosalind imports from; an account
is a Rosalind user.

Accounts are **just-in-time provisioned**: the first validated token for a
given `(issuer, subject)` creates the `account` + `account_identity` rows
(idempotent — re-authentication reuses them). The IdP is authoritative for
credentials; Rosalind only records the mapping.

**Accounts are identified only by `(issuer, subject)`.** Email and other
profile claims are mutable and must never be used to identify, match, or merge
accounts.

`self_person_id` is set explicitly, never inferred.
<!-- TODO: document how it is set (CLI command / API call) and any validation. -->

## Token validation (local JWKS)

Both FastAPI and MCP validate JWTs locally against Keycloak's JWKS
(`/realms/{realm}/protocol/openid-connect/certs`) using PyJWT. There is no
per-request call to Keycloak.

- signature (RS256) against the realm's public keys (cached, respects `kid`
  rotation);
- `iss` pinned to the realm issuer;
- `aud` must contain the configured resource identifier (`rosalind` by
  default, set via a Keycloak audience mapper);
- `exp` / `nbf` and required claims `iss`, `sub`, `exp`, `aud`.

The concrete verifier is
`backend/src/rosalind/adapters/outbound/keycloak/jwt.py`, wired through the
`TokenVerifier` port in `application/ports/identity.py`. The MCP adapter wraps
it (`adapters/inbound/mcp/verifier.py`). Token parsing and claim checks belong
in the verifier only — never in a route or tool handler.

## What is protected

- **FastAPI**: `people`, `sources`, and `imports` routers require a valid bearer
  token. `/health` and `/auth/google/callback` are intentionally open.
- **MCP**: `streamable-http` and `sse` transports require auth; the server
  publishes RFC 9728 Protected Resource Metadata and challenges with
  `WWW-Authenticate: Bearer`. `stdio` is local/trusted and unauthenticated.

### Protection policy

Every route and tool must be either authenticated or on an explicit,
justified public allowlist (currently `/health` and `/auth/google/callback`).

*Current mechanism:* routers opt in individually (e.g.
`dependencies=[Depends(get_current_account)]`), so a new router that forgets
the dependency is silently public.

*Recommended:* invert this — protect by default at the app/router level and
maintain the public allowlist explicitly — and add a test that enumerates all
registered routes and fails if any is neither protected nor allowlisted.

### `/auth/google/callback`

This endpoint is open because it is the OAuth callback for Google **as a data
provider** (a source account), not for user login. It must bind the flow to the
account that initiated it, otherwise a Google source could be attached to the
wrong account.
<!-- TODO: document how the flow is bound (signed `state`?) and how it is validated. -->

## "Who am I"

The current authenticated account is exposed as a derived projection of the
persisted `Account` plus the token's identity claims (`email`, name) — Keycloak
remains the source of truth for profile data; Rosalind only persists the
identity mapping. Profile claims are not stored.

- **REST**: `GET /me` → `{ account_id, self_person_id, created_at, subject,
  email, preferred_username, given_name, family_name }`.
- **MCP**: the read-only `get_my_profile` tool returns the same data.
- **CLI**: `rosalind auth whoami` prints it.

The CLI requests the `openid email profile` scopes, and `email` is a default
client scope on `rosalind-cli`, so the access token carries the profile claims.

<!-- TODO: document (a) the result when self_person_id is null, and
     (b) get_my_profile over unauthenticated stdio, where there is no account. -->

## CLI authentication (device flow)

The CLI is a public OAuth client (no client secret) and uses the Device
Authorization Grant:

```text
rosalind auth sign-in   → prints a URL + user code, opens browser, polls, stores tokens
rosalind auth sign-up   → same flow; the Keycloak page offers registration
rosalind auth sign-out  → clears local tokens + best-effort Keycloak revocation
rosalind auth whoami    → prints the authenticated account (id, email, name)
```

Tokens live in `~/.config/rosalind/credentials.json` (mode `0600`) and are
refreshed from the stored refresh token when expired or on a `401`.

## Authorization status

Authentication is implemented; authorization is not.

- Authenticated accounts are **not** scoped to their own data: `account_id` has
  not yet been retrofitted onto existing resources (`source_account`, imports,
  persons, …). Treat Rosalind as single-user until it is.
- MCP is read-only. Write tools stay deferred until an authorization (Actor)
  model exists; authentication alone is not sufficient.
- Uploads to object storage in the import flow: how they are authorized
  (presigned URLs vs. proxied through the API) is undecided.
  <!-- TODO: document once decided. -->

## Logging and secrets

- Never log bearer tokens, refresh tokens, `Authorization` headers, raw claim
  sets, or the contents of `credentials.json`.
- Log operational metadata only, such as the account id, outcome, and error
  class.
- `keycloak/rosalind-realm.json` must contain no secrets. The CLI is a public
  client and needs none; keep it that way.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ROSALIND_KEYCLOAK_URL` | `http://localhost:8080` | Keycloak base URL |
| `ROSALIND_KEYCLOAK_REALM` | `rosalind` | Realm name |
| `ROSALIND_KEYCLOAK_AUDIENCE` | `rosalind` | Expected `aud` in tokens |
| `ROSALIND_KEYCLOAK_CLIENT_ID` | `rosalind-cli` | Public client id (CLI) |
| `ROSALIND_AUTH_ENABLED` | `true` | Disable bearer checks for local dev/e2e |
| `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` | `admin` | Bootstrap admin (docker-compose) |
| `KEYCLOAK_DB_USER` / `KEYCLOAK_DB_PASSWORD` / `KEYCLOAK_DB_NAME` | `keycloak` | Dedicated Postgres database for Keycloak (docker-compose) |

`ROSALIND_AUTH_ENABLED=false` substitutes an anonymous token/account for local
development and e2e tests. It must never be set in a deployed environment.
Recommended: log a prominent warning at startup when it is off, and refuse to
start with it off in a production environment.

## Keycloak realm and docker-compose

The realm and clients are imported from `keycloak/rosalind-realm.json` on
container start (`start-dev --import-realm`), so no manual admin-console setup
is required. Keycloak persists realms, users, and sessions to a dedicated
`keycloak` Postgres database (`keycloak-db` service), so registrations survive
`docker compose down` / `up`.

### Re-importing the realm

Realm import runs only on first boot (when the realm does not yet exist). To
force a re-import after editing the realm file:

1. Stop and remove **only** the `keycloak` and `keycloak-db` services.
2. Delete **only** the Keycloak database volume (find its name with
   `docker volume ls`; it depends on the compose project name).
3. Start the stack again.

This deletes all Keycloak users and registrations, but leaves Rosalind data
untouched.

> **Do not use `docker compose down -v` for this.** It also drops the Rosalind
> Postgres and SeaweedFS volumes, which hold the immutable raw evidence layer.

### Required realm contents

The realm file must define the standard OIDC client scopes (`basic`, `profile`,
`email`, `roles`, `web-origins`, `acr`). Since Keycloak 25, the `sub` and
`auth_time` claims are emitted by protocol mappers on the `basic` scope, so
importing a realm with only custom scopes silently strips `sub` from access
tokens — and Rosalind requires `sub`.

### Registration

Registration uses **email as username** (`registrationEmailAsUsername: true`,
`editUsernameAllowed: false`): the registration form asks for first name, last
name, email, and password (no separate username field), and the Keycloak
username is derived from the email address.

## Production deployment

The shipped docker-compose setup is for development:

- Keycloak runs with `start-dev`, which is not a production mode.
- The bootstrap admin defaults to `admin` / `admin`.

A production deployment needs at least: Keycloak in production mode (`start`),
TLS, a configured hostname, real admin and database credentials supplied via
secrets, and `ROSALIND_AUTH_ENABLED` left at `true`.
<!-- TODO: expand into a deployment checklist once a target environment exists. -->
