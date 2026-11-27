# Rosalind — Access Policy Enforcement in the RAG (Implementation Step 2)

Companion to `rosalind_policy_engine_rag_filtering_v7.md` and `rosalind_policy_interpreter.md`. This document plans how **access-type policies** (permit and deny on exact selectors such as participants, accounts and dates) are enforced on every agent-facing read in Rosalind. It is the second implementation step.

> **Implementation status (Phase 2 v1).** The first enforcement slice is live behind
> `policy.access_enforcement_enabled` (default off) for the MCP `search` tool.
> Deviations from this plan, intentionally:
>
> - enforcement is `all_agents` only; per-agent identity is deferred;
> - when no permit policy exists the scope is **implicit permit-all** (deny rules
>   still apply), so no baseline-grant migration is required;
> - `search.chunk` carries `from/to/cc/bcc_handles` arrays, backfilled from
>   `core.email_participant`, instead of entity-ID arrays;
> - L1 SQL filtering and L2 independent verification are implemented; L3
>   restricted roles/views and RLS are deferred;
> - only `search` exists today, so `get_item`, `get_thread`, `get_context`,
>   attachment fetch and extractions are not yet in scope;
> - quoted/forwarded copies of denied text remain the documented Phase 5 gap.
>
> **Before enabling:** apply both Alembic chains (`just migrate` and
> `just policy-migrate`). The data migration `0022` backfills role handles and
> `0023` adds the policy audit columns; the policy chain adds
> `authz.policy_version` and `audit.security_event`. If the policy tables are
> missing or unreadable, scoped searches fail closed.
>
> **Per-level gates.** `policy.access_enforcement_levels` controls each stage:
> `lexical`, `semantic`, `listing`, `metadata`, `thread`, `assembly` and
> `verification`. All default to `true`. Disabling a retrieval, metadata or
> thread level is a degraded mode: output may still be filtered by `assembly`
> or `verification`, but ranking, counts, coverage or existence signals can
> leak. At least one of `assembly`/`verification` must remain enabled when the
> master flag is on, or the process refuses to start. The level set is part of
> the plan fingerprint and is recorded in `search.request_log.access_levels`.

---

## 1. Purpose and scope

Step 1 produced confirmed, persisted policies. Step 2 makes the access ones **real**: an agent only ever receives data that its active access policies allow, on every MCP tool and every internal read path behind them.

**What counts as an access constraint.** An access constraint is an exact condition on the stored attributes of an email (sender, recipients, account, date), so it can be decided by a SQL predicate without interpreting content. "No emails from John Smith" and "no emails before January 1st 2025" are access constraints. Step 2 is deliberately limited to this: **a pure SQL filter**. Anything that needs interpretation of text, including copies of denied text quoted inside other emails, belongs to later steps.

**In scope**

- Agent identity and the agent registry.
- The Policy Engine: loading active access policies and producing an `EffectiveScope` (main document, section 5).
- A scoped query layer that all agent-facing reads must go through (BM25, vector, hybrid, reranking input, item, thread, context, attachments, extractions, entities, capabilities).
- Data-model changes needed to filter fast and correctly.
- Side-channel hardening (not-found behaviour, counts, cursors, caches).
- Audit, the leak-test suite, performance benchmarks, rollout and migration.

**Out of scope (later steps)**

- Confidentiality policies: the semantic pipeline, overlay index, JIT verification, redaction markers inside text and the final gate (Phases 4 and 5). Confidentiality policies are loaded and carried in the scope, but **not applied** in this step.
- Quoted and forwarded copies of denied content inside visible emails (Phase 5, section 5.8).
- Content-based grants such as "flight reservations" (they need classification, and the interpreter already defers them).
- The full dashboard, probing protections and rate limiting (Phases 6 and 7).

**Result of this step:** the two example access constraints work end to end ("Agent A can't see emails from John Smith", "Agent Y can see my emails with John Smith"), with provable behaviour and a leak-test suite that gates releases.

---

## 2. Assumptions to verify (WP0)

We have not reviewed the Rosalind codebase for this plan. Everything below is assumed and must be checked in WP0. Table and column names in this document are illustrative.

| # | Assumption | Why it matters |
|---|---|---|
| A1 | PostgreSQL with pgvector (HNSW) and a BM25 extension, over a chunk table that has `email_id`. | The scope predicate must apply to every leg of retrieval. |
| A2 | Participants (from, to, cc, bcc) are stored with roles and resolved to entity IDs, with an unresolved-address state. | Selectors match on entities and roles. |
| A3 | The entity system has canonical IDs and merge and split operations. | Policies reference entity IDs and must follow merges. |
| A4 | MCP tools are the ones listed in section 5.9. | Each tool needs a declared enforcement. |
| A5 | Attachments are stored content-addressed or per email. | Blob IDs must not allow cross-email fetches. |
| A6 | Extractions and entity attributes carry provenance (source email IDs). | Derived data must follow the visibility of its sources. |
| A7 | **Whether quoted text is currently indexed** and how replies and forwards are stored. | Characterizes the known limitation in section 5.8 and informs Phase 5. |
| A8 | There is a single place where the MCP server calls the retrieval layer. | The choke point in section 4. |
| A9 | Agents authenticate to the MCP server with a credential that Rosalind controls. | Agent identity (section 5.1). |
| A10 | Existing agents currently see everything and there is no real agent traffic yet. | Migration (section 9). |

---

## 3. Principles

1. **One choke point.** Every agent-facing read goes through a single scoped reader that requires an `EffectiveScope`. There is no other path to email content for agent traffic.
2. **Default deny.** No agent, or no grant, means no data.
3. **Deny overrides permit.**
4. **Enforce in the query, not after it.** The scope is part of the SQL, so ranking, paging and counts are computed over the visible set only.
5. **Verify independently.** Every returned item is re-checked by a second, independent implementation of the same rules. A failure is a security event, not a normal condition.
6. **A denied item is indistinguishable from a missing one.**
7. **Fail closed on identity and policy errors.** An unknown agent, an unreadable policy or a failed scope load returns nothing.
8. **Take effect on the next request.** A policy change applies to any request that starts after it commits. There is no TTL cache for scopes.

---

## 4. Architecture

```text
MCP request (credential, tool, arguments)
        |
        v
[1] Authenticate -> agent_id, credential_id, request_id           (section 5.1)
        |
        v
[2] Open a REPEATABLE READ, READ ONLY snapshot                    (section 5.2)
    Load active access policies for agent_id
    Policy Engine -> EffectiveScope (policy_version, fingerprint) (sections 5.3, 5.4)
        |
        v
[3] ScopedReader (the only way to read data for an agent)         (section 5.5)
    - compile scope to SQL predicates
    - choose retrieval strategy (BM25 / exact vector / ANN)
    - retrieve in the same snapshot
        |
        v
[4] Verify every returned item against the reference evaluator    (section 5.7)
        |
        v
[5] Assemble: render fields and thread placeholders              (section 5.9)
        |
        v
[6] Respond, then write the audit entry                           (section 5.11)
```

**Extension points for Phases 4 and 5.** The semantic work plugs into the same pipeline without changing its shape. The overlay join goes into stage 3, JIT verification into stage 4, and marker rendering and the final gate into stage 5. `EffectiveScope` already carries the list of pending confidentiality policies for this reason.

**Defence in depth, three layers**

| Layer | Mechanism | Catches |
|---|---|---|
| L1 | Scope compiled into every query | Normal enforcement. |
| L2 | Post-retrieval verification by an independent evaluator | A bug or forgotten predicate in L1. |
| L3 | Restricted DB role and views for the agent-facing service | Code that bypasses the gateway. |

---

## 5. Components

### 5.1 Agent identity and context

- Each registered agent has an `agent_id`, a status (`active`, `suspended`) and one or more credentials.
- The principal is the **credential's agent**, not the model behind it. Two LLMs behind one MCP client are the same agent.
- Credentials are random secrets stored hashed, rotatable, and revocable individually. The MCP server maps a credential to `agent_id` on every request.
- Unknown, revoked or suspended credentials get the same generic error and no data.
- A request context object (`agent_id`, `credential_id`, `request_id`) is created at stage 1 and is required by the scoped reader. Nothing in agent-facing code reads it from request arguments.
- **Kill switch:** suspending an agent denies everything on the next request. A global deny-all flag exists for incidents.

### 5.2 Policy loading, versioning and snapshot consistency

- Active access policies for the agent are loaded **on every request**, in the same `REPEATABLE READ, READ ONLY` transaction that runs the data queries. The scope and the data come from one consistent snapshot, so a policy change cannot be half-applied inside one request.
- `policy_version` is a monotonically increasing counter. It is bumped when any of these change: a policy revision or its status, an agent status, an entity merge or split touching an entity referenced by an active policy, or the address list of a referenced entity.
- No scope is cached by time. If loading proves costly, caching is allowed only keyed by `policy_version`, validated by a cheap version read on every request.
- Only `active` access policies participate. `building`, `needs_review`, `paused`, `revoked` and `failed` do not.
- Confidentiality policies are loaded and copied into `pending_semantic` in the scope, but are ignored by enforcement in this step.

### 5.3 Selector grammar and semantics

The access selector in `PolicySpec` is pinned for v1:

```text
Selector :=
    { "operator": "all" }
  | { "operator": "has_participant", "entity_id": ID, "roles": [from|to|cc|bcc] }
  | { "operator": "in_accounts",     "account_ids": [ID] }
  | { "operator": "date_between",    "from": instant|null, "to": instant|null }   // [from, to)
  | { "operator": "all_of",          "terms": [Selector] }                         // AND
```

- **OR is expressed by several policies**, not inside a selector. "Emails from John or Mary" is two policies.
- A role list means any of those roles ("any" is the full list).
- `date_between` is half-open on the email's canonical timestamp, in UTC. The interpreter freezes dates at confirmation.
- Every email attribute used by a selector is known at ingestion time.

**Visibility semantics.** For an agent and an action:

```text
visible(email) = ( OR over permit policies P of  match(P, email) )
                 AND NOT ( OR over deny policies D of match(D, email) )
```

With no permit policy, nothing is visible. A deny with selector `all` hides everything.

**Per-action scopes.** Policies carry an `actions` list. A tool needs one or more actions (section 5.9), and its scope is the **intersection** of the scopes of those actions. This is conservative and simple. The interpreter currently grants all four actions together, so in practice the scopes are identical.

**Participant matching and unresolved addresses.**

| Selector use | Match rule | Failure mode |
|---|---|---|
| Permit | Entity ID only | An address not yet linked to the entity is not granted (under-share, safe). |
| Deny | Entity ID **or** any known address of the entity | A new address not yet on the entity leaks until it is resolved. Documented limitation (section 11). |

Entity IDs are canonical: policy evaluation resolves redirects after merges.

### 5.4 EffectiveScope v1

```json
{
  "decision": "SCOPED",
  "agent_id": "agent_a",
  "actions": ["email.search", "email.read_content"],
  "policy_version": 12,
  "permit": [ { } ],
  "deny": [
    { "participants": [
        { "entity_ids": ["person_123"],
          "addresses": ["john.smith@acme.com"],
          "roles": ["from"] } ] }
  ],
  "pending_semantic": [ { "policy_id": "pol_41", "statement_id": "st_17", "status": "building" } ],
  "scope_fingerprint": "sf_a_7c1e"
}
```

- A **clause** is an AND of its present parts: `account_ids`, `date`, and a list of `participants` terms. An empty clause `{}` matches every email.
- `all_of` is flattened into one clause. Identical clauses are deduplicated.
- If the permit list is empty, or any deny clause is empty, the decision is `DENY_ALL` and no data query is run. The response shape and path match a normal empty result.
- `scope_fingerprint` is a hash of the canonical, sorted clause lists. It keys caches and cursors.

### 5.5 Scoped query layer

`ScopedReader` is the only component that reads email data for agents.

- Its methods take `(ctx, scope, ...)`. The query builder cannot produce a query without a scope, by type.
- It compiles the scope to predicates on indexed columns (section 5.6) and applies them **to every leg**: BM25, vector, any "similar emails" lookup, neighbour expansion and counts.
- Reranking receives only candidates that passed the scope. The reranker must be local.

**Predicate shape** (illustrative names):

```sql
-- Agent A: permit {all}, deny {from John Smith}
SELECT c.id AS chunk_id, c.email_id, <bm25 score> AS score
FROM search.chunk c
WHERE <bm25 match on :query>
  AND NOT (c.from_entity_ids && :deny_entity_ids_1
           OR c.from_addresses && :deny_addresses_1)
ORDER BY score DESC
LIMIT :k;
```

Role sets map to columns: `{from}` uses `from_*`, `{to}` uses `to_*`, and so on. A full role list uses the combined `participant_*` columns.

**Vector retrieval strategy.** HNSW with a selective filter can return far fewer than k rows, because the filter is applied after the index scan. The reader chooses a strategy from the size of the scoped set:

```text
n = scoped_chunk_count(scope)        # cached per (scope_fingerprint, ingestion epoch)
if n <= EXACT_MAX:    exact scan over the scoped rows only (ORDER BY distance)
else:                 ANN with iterative scan and a bounded scan limit;
                      if fewer than k results come back -> exact fallback over the scoped rows
```

`EXACT_MAX` and the scan limits are set by the benchmark (section 7.3). The iterative-scan feature depends on the pgvector version, which WP0 must verify. Pagination uses keyset ordering over the same scoped set.

**Hybrid search.** The scope is applied to each leg before fusion, with enough candidate depth per leg that fusion has real choices.

**Item and thread reads** use a single query with the scope in the `WHERE` clause (`WHERE id = :id AND <scope>`), never fetch-then-check. This gives the same path and the same result shape for "denied" and "does not exist".

### 5.6 Data model changes

Names are illustrative. WP0 maps them to the real schema.

| Change | Purpose |
|---|---|
| On the email and chunk rows: `account_id`, `sent_at` (UTC), `from_entity_ids`, `to_entity_ids`, `cc_entity_ids`, `bcc_entity_ids`, `participant_entity_ids`, and matching `*_addresses` arrays | Selectors become indexable predicates without joins. |
| GIN indexes on the entity and address arrays, B-tree on `account_id` and `sent_at` | Fast overlap and range checks. |
| `public_id` on emails, attachments and threads: a random 128-bit ID used by agents | Sequential IDs would reveal counts and ordering. Internal keys never leave the service. |
| `authz.entity_redirect` and a merge hook that rewrites the arrays and bumps `policy_version` | Merges and splits propagate to policies and denormalized data. |
| `authz.agent`, `authz.agent_credential` | Section 5.1. |
| A consistency job comparing the arrays with the participants table | Catches drift. A mismatch is an alert. |

The arrays are written at ingestion and by the merge hook. The backfill is a one-off migration with a progress report.

### 5.7 Second layer: verification, and the third layer: restricted DB access

**L2: post-retrieval verification.** After retrieval and before assembly, a batched lookup fetches the authorization attributes of every returned item ID (account, timestamp, participants with roles, addresses) and runs a **reference evaluator** written independently in Python. Any item that fails is dropped, a `security_event` is written, and an alert is raised. In healthy operation this never fires.

- The attribute lookup uses a separate DB role that can read only authorization columns, not content.
- The reference evaluator is also the oracle for the property tests (section 7.1), so it is exercised constantly.

**L3: restricted DB role.** The agent-facing service connects with a role that has no direct access to raw content tables. It reads through views and functions that expose only the columns the gateway needs, never raw MIME or raw bodies. This limits the blast radius of code that bypasses the gateway.

**RLS.** PostgreSQL row-level security would add a database-enforced layer, but a per-row policy function interacts badly with index scans and HNSW. It is **evaluated by benchmark in WP4**, not assumed. If it is cheap enough, it can be added as L4. Open decision 1.

### 5.8 Quoted and forwarded content (not in this step)

Step 2 is a pure SQL filter, so it does not handle text from a denied email that appears inside another, visible email. Example: Mary's reply (visible) quotes John's message (denied).

**Known limitation in step 2**

- A deny rule hides the denied emails themselves, their attachments and their derived data, but **not copies of their text inside visible emails** (quoted replies, forwarded messages).
- Depending on whether quoted text is indexed (assumption A7), those copies can appear in search hits, snippets, `get_item` and `get_thread`.
- The limitation is stated in the interpreter preview for deny rules, and recorded in the leak tests as expected-failure cases (section 7.2), so that it stays visible.

**Planned handling (Phase 5)**

Masking of quoted and forwarded copies is scheduled for Phase 5, on top of the segment store (stable content hashes per segment). A segment whose hash matches a segment of a denied email is replaced by the marker, as described in section 7.2 of the main document. Whether Phase 5 also needs attribution-based parsing of replies and forwards is open decision 4.

**What WP0 does now:** it records whether quoted text is indexed and how replies and forwards are stored, so the exposure is characterized before step 2 ships.

### 5.9 Per-tool behaviour

| Tool | Actions required | Behaviour under scope | Denied or hidden case |
|---|---|---|---|
| `search` | `email.search` + `email.read_content` | Scoped retrieval, verification, snippets from visible content only. Totals omitted or computed in-scope. | Items simply do not appear. |
| `get_item` | `email.read_content` | `WHERE id AND scope`; body rendered as stored (quoted copies are not masked, section 5.8). | Same "not found" as an unknown ID. |
| `get_thread` | `email.read_content` | Each message checked. Thread subject, participant list, message count and dates are computed over visible messages only. | A denied message becomes one placeholder (uniform marker, no sender, date or size). Adjacent denied messages merge into one placeholder. If nothing is visible, "not found". |
| `get_context` | `email.read_content` | Neighbours (by time or thread) are fetched through the scoped reader. | Skipped neighbours do not appear. |
| Attachment fetch | `email.read_attachment` + parent email visible | Attachment IDs are bound to `(email_id, part)`. No fetch by content hash. | "Not found". |
| `list_extractions` | `email.read_extraction` | An extraction is visible only if **all** of its evidence emails are visible. | Hidden (open decision 2). |
| `find_entity` | `email.read_content` | The entity record stays findable (open decision 3). Derived attributes (interaction counts, last contact, role or title extracted from signatures) are computed only from visible emails and hidden if their evidence is not visible. | Derived fields omitted. |
| `describe_capabilities` | any | Accounts, date coverage and counts reflect the agent's visible set only. | No mailbox-wide totals. |
| Autocomplete, facets, suggestions, analytics | as the underlying read | Computed in-scope. | |

**Rule for new tools:** a tool must declare its required actions and use the scoped reader. CI fails otherwise (section 7.4).

### 5.10 Side channels

| Channel | Control |
|---|---|
| Denied vs missing | One scoped query, one response shape, one error code and message for both. |
| IDs | Random public IDs. No sequential or time-ordered IDs. |
| Timing | No data-dependent early exits between the denied and missing paths. We test that the distributions are close. We do not promise constant time. |
| Counts and totals | Omitted by default (`has_more` only). Any count is computed in-scope. |
| Pagination | Signed cursors (HMAC with a server-side key), bound to `agent_id`, `scope_fingerprint`, `policy_version` and the query. A mismatch returns a generic "cursor expired". |
| Caches | Result caches, if any, are keyed by `scope_fingerprint`. Nothing is shared across agents with different scopes. Query-embedding caches are keyed by text only and are safe. |
| Errors and logs | Generic errors to agents. Logs hold IDs and codes, never content. |
| Placeholders | Uniform marker. Adjacent denied items merge. |

### 5.11 Audit and security events

- `audit.request_log`: `request_id`, `agent_id`, `credential_id`, tool, actions, `policy_version`, `scope_fingerprint`, decision, number of items returned, number masked or dropped, duration. No content and no queries.
- `audit.security_event`: L2 verification failures, cursor tampering, unknown-credential attempts, consistency-job mismatches. Alerts on any L2 failure.
- Every request writes an entry, including `DENY_ALL` and errors.

---

## 6. Worked example

**Mailbox**

| Email | From | To / Cc | Content |
|---|---|---|---|
| E5 | me | Anna | "I have cancer, let's meet tomorrow at 10am." |
| E6 | John Smith | me | "Quarterly numbers attached." |
| E7 | Mary | me, cc John Smith | "Thanks, will review." plus a quoted block of E6 ("On Tue, John Smith wrote: > Quarterly numbers attached.") |

**Policies**

- Agent A: `P1 permit {all}` (a baseline grant) and `P2 deny has_participant(person_123 = John Smith, roles [from])`.
- Agent Y: `P3 permit has_participant(person_123, roles [from, to, cc, bcc])`.

**EffectiveScope**

```text
Agent A: permit [ {} ], deny [ { participants: [ { entity_ids: [person_123], addresses: [john.smith@acme.com], roles: [from] } ] } ]
Agent Y: permit [ { participants: [ { entity_ids: [person_123], roles: [from,to,cc,bcc] } ] } ], deny []
```

**What each agent gets**

| Request | Agent A | Agent Y |
|---|---|---|
| `search("quarterly numbers")` | E6 is denied, so no hit on it. E7 can still be a hit if quoted text is indexed (known limitation). | E6 (from John), and E7 if quoted text is indexed. |
| `get_item(E5)` | Visible. The confidentiality rule from step 1 is not applied yet (Phases 4 and 5 handle "cancer"). | Not found (no John). |
| `get_item(E6)` | Not found. | Visible. |
| `get_item(E7)` | Visible, including the quoted block of E6, shown as stored (known limitation until Phase 5). | Visible. |
| `get_thread(E6)` | One placeholder for E6, then E7 (its quote is shown as stored). | E6 and E7. |
| `find_entity("John Smith")` | Found. Interaction count and last-contact date computed from E7 only. | Found, with E6 and E7 in the stats. |

E7 shows the known limitation: Agent A is denied E6, but E6's text reaches Agent A through Mary's reply until Phase 5.

**Verification.** For every item returned, L2 recomputes visibility from the item's participants, account and timestamp. For Agent A, E6 can never pass.

---

## 7. Testing and evaluation

### 7.1 Correctness

- **Unit tests:** precedence (default deny, deny over permit, empty permit, deny-all), role handling, half-open date boundaries and timezones, entity merges and redirects, unresolved participants, fingerprint stability.
- **Property tests:** generate random policy sets and random emails, compute the visible set with the **reference evaluator**, run the SQL compiled from the scope on a test database, and require identical results. This ties L1 and L2 together.

### 7.2 Leak tests

Built on a synthetic mailbox with planted **canary strings** in denied content, including attachments and extractions. Canaries in quoted copies of denied emails are also planted, but only as **expected-failure tests** that document the known limitation (section 5.8). They are not part of the gate until Phase 5.

- An adversarial agent client tries every tool: searching canary words and semantic neighbours, fetching IDs, walking threads, listing extractions, reading entity stats, tampering with cursors, and reusing cursors across agents.
- The release gate is **zero canary exposure**, excluding the expected-failure quoted-copy canaries.
- Differential test: two agents with different scopes run the same queries in interleaved order. Nothing from one leaks into the other (caches, cursors).
- Denied vs missing: compare response bodies exactly and timing distributions approximately.
- **Mutation test:** deliberately break a predicate and confirm L2 catches it and raises a security event.

### 7.3 Performance and recall

- Baseline: unscoped latency on the real data size.
- Scoped latency for BM25, vector and hybrid, across a range of selectivities (a handful of permitted emails to nearly everything).
- **Vector recall under selective filters:** compare ANN results with exact search over the permitted set. This sets `EXACT_MAX`, scan limits, and decides whether RLS (L4) is affordable.
- L2 overhead per request.
- Targets are set after the baseline measurement in WP0.

### 7.4 Structural checks in CI

- A test enumerates all MCP tools and fails if any lacks declared actions or does not use the scoped reader.
- A lint or import rule forbids agent-facing modules from importing the raw DB access layer.
- The leak-test suite and the property tests run on every change.

---

## 8. Work packages and sequencing

| WP | Name | Content | Exit criteria |
|---|---|---|---|
| WP0 | Discovery and baseline | Verify assumptions A1 to A10. Inventory every read path (tools, caches, background readers, exports, logs). Measure the baseline. Map illustrative names to the real schema. | Read-path inventory table, schema map, baseline numbers, decisions on the open questions that block design. |
| WP1 | Agent identity | Registry, credentials, suspension, request context, kill switch. | Unknown or suspended credentials get nothing. |
| WP2 | Data model | Denormalized attributes, GIN indexes, public IDs, entity redirect and merge hook, consistency job, backfill. | Backfill complete, consistency job green. |
| WP3 | Policy Engine | Loader, versioning, selector grammar, `EffectiveScope`, fingerprint, reference evaluator. | Property-test oracle in place. |
| WP4 | Scoped query layer | `ScopedReader`, SQL compilation, retrieval strategy selector, L2 verification, L3 role and views, RLS benchmark. | Property tests pass, recall and latency targets met. |
| WP5 | Tool integration | All tools in section 5.9, side-channel controls, cursors, placeholders, extraction and entity rules. | Leak tests pass for every tool. |
| WP6 | Audit and security events | Request log, security events, alerts. | Every request audited. |
| WP7 | Test harness | Synthetic mailbox with canaries, adversarial client, benchmarks, CI gates. Shared with the Phase 3 spike. | Gates run in CI. |
| WP8 | Rollout and migration | Section 9. | Acceptance criteria met. |

**Order:** WP0 first. WP1 and WP2 in parallel. Then WP3, WP4 and WP5 in sequence. WP6 (audit) runs alongside WP4 and WP5. WP7 (test harness) starts at the beginning and grows with each package. WP8 (rollout) is last.

---

## 9. Rollout and migration

- **Enforcement mode per agent:** `enforce` (default) or `shadow`. In shadow mode the scope is computed and the differences against what the agent would receive are logged, without changing the response. It is meant for the owner's own test agents only. Shadow mode is never a way to run a real agent unrestricted.
- **Default deny breaks existing integrations.** An agent with no grant sees nothing after this step. For existing agents, the migration creates explicit **baseline grants** (`permit {all}`, marked `source.kind = migration`) so behaviour is unchanged until the owner narrows it, or the owner is asked to choose per agent (open decision 5). They show in the dashboard as migrated grants.
- **Deny-only agents.** A deny with no permit does nothing, because default deny already hides everything. The interpreter should warn when a deny is created for an agent with no matching grant and offer a baseline grant in the same confirmation (section 10).
- **Interpreter preview flag.** When the acceptance criteria pass, the `enforcement_available` flag (interpreter document, section 5.8) is turned on, so previews say "Takes effect immediately" and stop saying "not active". Confidentiality policies keep the "not enforced yet" notice until Phases 4 and 5. Deny previews also state that quoted copies of denied text are not hidden yet.
- **Runbook:** suspend an agent, roll back a policy revision, set the global deny-all flag, investigate an L2 alert.

---

## 10. Follow-ups to other documents

**Interpreter document**

1. Pin the v1 selector grammar (section 5.3). A prompt naming several people becomes several policies, not a list in one selector. Add the `all` selector and a "can see all my emails" phrasing.
2. Stage 7 (impact and conflicts): for a deny on an agent with no matching permit, warn that the rule changes nothing yet and offer a baseline grant.
3. Flip the `enforcement_available` flag after acceptance.
4. Access deny previews state that text from the denied emails that appears quoted inside other emails is not hidden yet (until Phase 5).

**Main document**

- Roadmap: this step is Phase 2, and the spike moves to Phase 3. Masking of quoted and forwarded copies of denied content is in Phase 5, not in this step (in v7).
- Section 7.4 names RLS as defence in depth. This plan proposes post-retrieval verification as the second layer and benchmarks RLS (open decision 1).

---

## 11. Risks and limitations

| Risk | Mitigation or note |
|---|---|
| Unresolved or newly added addresses of a denied person | Deny matches known addresses as well. A new address not yet linked leaks until resolution. Entity-resolution lag is monitored. |
| Entity merge or split changes who a policy refers to | The merge hook bumps `policy_version` and rewrites arrays. A consistency job alerts on drift. |
| Vector recall collapse under selective filters | Strategy selector with exact fallback, measured recall. |
| A forgotten read path (new tool, cache, export) | Read-path inventory in WP0, CI structural checks, L2 verification, L3 role. |
| Copies of denied text inside visible emails (quotes, forwards) | Not handled in step 2. This is a real leak path for sender deny rules. Stated in the preview, tracked by expected-failure tests, handled in Phase 5. |
| Role derivation ambiguities (Sender, Reply-To, mailing lists, "on behalf of", missing Bcc) | Rules fixed in WP0 (open decision 7). |
| Timing differences between denied and missing | Single query path, tested. Not guaranteed constant. |
| Scope races inside a request | One snapshot for scope and data. |
| Performance cost of scoping and L2 | Denormalized indexed arrays, batched verification, benchmarks with targets. |
| Default deny breaking existing agents | Migration baseline grants (section 9). |
| Cursor signing key management | Key stored outside the DB, rotation supported, old cursors expire. |

---

## 12. Acceptance criteria

- Both example constraints work end to end on every tool in section 5.9.
- The leak-test suite reports **zero canary exposure** across attachments, extractions and entity stats, and the quoted-copy canaries are recorded as known failures.
- The property tests show the SQL results equal to the reference evaluator on all generated cases.
- A denied item and a missing item are indistinguishable in responses, and their timing distributions are close.
- A policy change, a suspension and an entity merge take effect on the next request.
- Every request is audited, and L2 raises an alert when a mutation test breaks a predicate.
- CI fails for any tool without declared actions or any agent-facing import of the raw DB layer.
- Vector recall under selective filters and latency meet the targets set after the WP0 baseline.
- No agent-facing code path exists outside the scoped reader (verified in WP0 inventory and by the CI checks).
- Interpreter previews state truthfully whether enforcement is active.

---

## 13. Open decisions

1. **Second and fourth layers:** post-retrieval verification as L2 (proposed), and whether RLS is added as L4 depending on the benchmark. Alternative: RLS as the second layer.
2. **Extraction visibility:** visible only if all evidence emails are visible (default, conservative), or if any is. The default hides some facts that could be derived from visible evidence.
3. **Entity visibility** (main document, decision 7) and the rule that derived entity attributes follow the visibility of their evidence.
4. **Phase 5 approach to quoted and forwarded copies:** segment content-hash matching only, or also attribution-based parsing of replies and forwards. Not needed for step 2 (decided: step 2 is a pure SQL filter).
5. **Migration:** automatic baseline grants for existing agents (proposed), or require the owner to choose per agent.
6. **Deny-only agents:** warn in the interpreter and offer a baseline grant (proposed), or leave as is.
7. **Role derivation rules:** how `from`, `to`, `cc`, `bcc` are derived from `From`, `Sender`, `Reply-To`, `Delivered-To`, mailing lists and "on behalf of". Whether Reply-To counts as a participant.
8. **Date selector timestamp:** sent time or received time, and the canonical timezone.
9. **Totals and counts:** omit by default (proposed) or compute in-scope.
10. **Thread placeholders:** merge adjacent denied messages into one (proposed) or one per message.
11. **Cursor design:** signed stateless (proposed) or server-side stored.

---

## 14. References

- pgvector, including iterative index scans (verify support in the installed version): https://github.com/pgvector/pgvector
- PostgreSQL, Row Security Policies: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- PostgreSQL, Transaction Isolation: https://www.postgresql.org/docs/current/transaction-iso.html
