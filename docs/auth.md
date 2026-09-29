# Authentication & Authorization

Rosalind delegates identity to **Keycloak** (OIDC / OAuth 2.1) and only ever
validates bearer tokens — it never issues credentials or stores passwords. The
REST API and the MCP server validate the same way, using the same token
verifier.

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

Accounts are **just-in-time provisioned**: the first validated token for a
given `(issuer, subject)` creates the `account` + `account_identity` rows
(idempotent — re-authentication reuses them). The IdP is authoritative for
credentials; Rosalind only records the mapping.

## Token validation (local JWKS)

Both FastAPI and MCP validate JWTs locally against Keycloak's JWKS
(`/realms/{realm}/protocol/openid-connect/certs`) using PyJWT:

- signature (RS256) against the realm's public keys (cached, respects `kid`
  rotation);
- `iss` pinned to the realm issuer;
- `aud` must contain the configured resource identifier (`rosalind` by
  default, set via a Keycloak audience mapper);
- `exp` / `nbf` and required claims `iss`, `sub`, `exp`, `aud`.

The concrete verifier is
`backend/src/rosalind/adapters/outbound/keycloak/jwt.py`, wired through the
`TokenVerifier` port in `application/ports/identity.py`. The MCP adapter wraps
it (`adapters/inbound/mcp/verifier.py`).

## What is protected

- **FastAPI**: `people`, `sources`, and `imports` routers require a valid bearer
  token. `/health` and `/auth/google/callback` are intentionally open.
- **MCP**: `streamable-http` and `sse` transports require auth; the server
  publishes RFC 9728 Protected Resource Metadata and challenges with
  `WWW-Authenticate: Bearer`. `stdio` is local/trusted and unauthenticated.
- New routers/tools must opt in explicitly.

## CLI authentication (device flow)

The CLI is a public OAuth client and uses the Device Authorization Grant:

```text
rosalind auth sign-in   → prints a URL + user code, opens browser, polls, stores tokens
rosalind auth sign-up   → same flow; the Keycloak page offers registration
rosalind auth sign-out  → clears local tokens + best-effort Keycloak revocation
```

Tokens live in `~/.config/rosalind/credentials.json` (mode `0600`), are never
logged, and are refreshed from the stored refresh token when expired or on a
`401`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ROSALIND_KEYCLOAK_URL` | `http://localhost:8080` | Keycloak base URL |
| `ROSALIND_KEYCLOAK_REALM` | `rosalind` | Realm name |
| `ROSALIND_KEYCLOAK_AUDIENCE` | `rosalind` | Expected `aud` in tokens |
| `ROSALIND_KEYCLOAK_CLIENT_ID` | `rosalind-cli` | Public client id (CLI) |
| `ROSALIND_AUTH_ENABLED` | `true` | Disable bearer checks for local dev/e2e |
| `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` | `admin` | Bootstrap admin (docker-compose) |

The realm and clients are imported from `keycloak/rosalind-realm.json` on
container start (`start-dev --import-realm`), so no manual admin-console setup
is required.

Registration uses **email as username** (`registrationEmailAsUsername: true`,
`editUsernameAllowed: false`): the registration form asks for first name, last
name, email, and password (no separate username field), and the Keycloak
username is derived from the email address.
