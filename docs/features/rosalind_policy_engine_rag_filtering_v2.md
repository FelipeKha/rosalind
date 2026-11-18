# Rosalind — Policy Engine & RAG Filtering (v2)

## 1. Objective

Rosalind allows users to own their personal data, store it in a self-hosted data warehouse and expose it to external AI agents through MCP.

The objective of the authorization system is to let users control precisely what each external agent can access or learn from their personal data.

Authorization must be:

- **Agent-specific:** Different agents can have different permissions.
- **Fine-grained:** The unit of protection is the *piece of information*, not the email and not a category of emails. If an email says "I have cancer, let's meet tomorrow at 10am", an agent restricted from the diagnosis must still learn that a meeting is set for tomorrow at 10am.
- **Semantic:** Restrictions cover information that is stated, paraphrased or strongly implied, not just keyword matches.
- **Seamless:** The user writes a rule in natural language and manages rules in a dashboard. The system decides internally how each rule is enforced.
- **Asynchronous and transparent:** Semantic rules take time to build. The user always knows whether a rule is ready, building, or needs attention.
- **Non-blocking by default:** A rule that is not ready yet does not block the agent. The user is told it is not enforced yet. Holding access until ready is an opt-in setting.
- **Model-independent:** Authorization is controlled by Rosalind, regardless of which external LLM or agent is used.
- **Enforced internally:** Sensitive content and policy interpretation are never sent to external models.

The system consists of three parts:

1. **Policy Engine:** Evaluates which rules apply to an agent and produces an `EffectiveScope`.
2. **Semantic Pipeline:** Finds protected information inside data at the span level and builds sanitized views of it. Runs asynchronously.
3. **RAG Filtering:** Applies the scope and the sanitized views during retrieval and context construction.

### 1.1 Two kinds of enforcement (internal, not user-facing)

| Kind | Examples | Nature |
|---|---|---|
| Exact scoping | Agent grants, participants, accounts, dates | Deterministic and provable. |
| Semantic protection | "Don't let Agent X know I have cancer" | Model-based, best-effort, measured by recall. |

The user does not choose between them. The interpreter routes each rule to the right mechanism. The dashboard shows how each rule is enforced. Semantic rules show a coverage figure and are labelled as AI-detected, not as guaranteed.

---

## 2. High-level architecture

```text
                  USER
                    |
                    | "Agent X should not know I have cancer"
                    v
          +-----------------------+
          |  Policy Interpreter   |   local NLP, entity resolution
          +-----------------------+
                    |  PolicySpec (validated, user-confirmed)
                    v
          +-----------------------+
          |    Policy Registry    |   PostgreSQL, immutable revisions
          +-----------------------+
                    |
          +---------+-----------------------------+
          |                                       |
          v                                       v
+-----------------------+            +---------------------------+
|     Policy Engine     |            |     Semantic Pipeline     |
| Python evaluator      |            | (async, per active rule)  |
| Grants, denies,       |            | Segmentation              |
| precedence            |            | Candidate generation      |
| -> EffectiveScope     |            | Verification (local model)|
+-----------------------+            | Span store + provenance   |
          |                          | Sanitized views (overlay) |
          |                          +---------------------------+
          |                                       |
          v                                       v
          +---------------------------------------+
          |             RAG Filtering             |
          | Hard scope predicates                 |
          | Base index minus affected segments    |
          |   plus agent's sanitized overlay      |
          +---------------------------------------+
                    |
                    v
          +-----------------------+
          | Reranking (local only)|
          +-----------------------+
                    |
                    v
          +-----------------------+
          |   Context Assembly    |
          | Sanitized rendering   |
          | Dedup, provenance     |
          | Final semantic gate   |
          +-----------------------+
                    |
                    v
              EXTERNAL AGENT  <--  MCP
```

---

## 3. Policy model

Rosalind maintains a canonical, versioned policy representation called `PolicySpec`. It is stored as JSONB in PostgreSQL and is independent of how it is evaluated.

### 3.1 Access policies (exact scoping)

Access policies specify what an agent is explicitly permitted to access.

> Agent Y can see my emails with John Smith.

```json
{
  "schema_version": "rosalind.policy.v2",
  "type": "access",
  "effect": "permit",
  "principal": { "type": "agent", "id": "agent_y" },
  "actions": ["email.search", "email.read_content", "email.read_attachment"],
  "resource": {
    "type": "email",
    "selector": {
      "operator": "has_participant",
      "entity_id": "person_123",
      "roles": ["from", "to", "cc", "bcc"]
    }
  },
  "status": "active"
}
```

The contact's name is resolved to a canonical Rosalind entity ID. If resolution is ambiguous (two "John Smith"), no grant is created and the policy waits in `needs_review`.

Content-based grants ("my travel agent can access flight and hotel reservations") use the semantic pipeline to identify matching emails. They are allow-lists, so they fail safe: until the build is ready, the agent simply has no access through that grant.

### 3.2 Confidentiality policies (protected information)

Confidentiality policies specify information an agent must not learn. The protected item is a **statement about the world**, not a category label.

> Agent X should not know that I have cancer.

```json
{
  "schema_version": "rosalind.policy.v2",
  "type": "confidentiality",
  "effect": "deny",
  "principal": { "type": "agent", "id": "agent_x" },
  "actions": [
    "email.search",
    "email.read_content",
    "email.read_attachment",
    "email.read_extraction"
  ],
  "resource": {
    "type": "protected_information",
    "kind": "fact",
    "statement": "The user has cancer",
    "subject": { "type": "entity", "id": "person_self" },
    "match_levels": ["asserts", "implies", "evidence"]
  },
  "treatment": {
    "mode": "redact_span",
    "fallback": "drop_segment"
  },
  "enforcement": { "hold_until_ready": false },
  "status": "building"
}
```

| Field | Meaning |
|---|---|
| `kind` | `fact` (a specific statement) or `topic` (e.g. "my financial information"). Both are enforced at span level, never by blocking whole emails. |
| `match_levels` | `asserts`: states or paraphrases it. `implies`: entails it ("my oncologist said the scan is clear"). `evidence`: strongly suggestive ("chemotherapy on Thursday"). Weak or ambiguous evidence is handled by classifier thresholds and the final gate (see section 6.3). |
| `treatment.mode` | `redact_span` removes only the protected span. `drop_segment` removes the whole sentence or clause. |
| `treatment.fallback` | Used when a clean redaction cannot be verified. The fallback is the smallest enclosing segment, never the whole email. |
| `hold_until_ready` | Opt-in. If true, the agent cannot read affected data until the rule is ready. Default is false. |

### 3.3 Precedence and failure behaviour

- **Access:** default deny. No grant means no access.
- **Denies override permits.** A permitted email is still subject to span-level confidentiality rules.
- **Confidentiality rules apply regardless of user-requested search filters.**
- **Rules that are not ready are not enforced, and the user is told.** The rule is never silently treated as active. If `hold_until_ready` is set, the affected data is withheld instead.
- **Ambiguous rules** (unresolved entity, unclear statement) stay in `needs_review`, and the user is notified.
- **Compilation or validation failure** rejects the revision. The previous active revision keeps applying.

### 3.4 Policy lifecycle

| Status | Meaning | User sees |
|---|---|---|
| `draft` | Interpreter output, not confirmed. | Preview. |
| `building` | Confirmed. The semantic build is running over existing data. | "Not yet enforced. 41% processed." |
| `active` | Existing data fully processed. New items are handled incrementally. | "Active", plus a pending-items count. |
| `needs_review` | Ambiguity or low-confidence resolution. | A request to clarify. |
| `failed` | Build error. | An error and a retry action. |
| `paused` / `revoked` | Disabled by the user. | The state. |

---

## 4. Policy creation and storage

Users create policies through a natural-language box.

- "Agent X should not know that I have cancer."
- "Agent Y can see my emails with John Smith."
- "My travel agent can access flight and hotel reservations."
- "Agent Z should not see my financial information."

### 4.1 Local policy interpretation

User instructions are themselves sensitive, so interpretation happens inside Rosalind.

```text
Natural language
      |  Intent classification
      v
Slot extraction (agent, subject, statement, scope)
      |  Entity resolution
      v
PolicySpec construction
      |  Pydantic / JSON Schema validation
      v
Preview and user confirmation
      |
      v
Storage, then async build
```

The interpreter has access to registered agents, the entity directory and the PolicySpec schema. It does not need access to the email archive. It never produces SQL or executable policy code, only a validated PolicySpec.

Deterministic parsing handles common phrasings. A local LLM (Ollama or llama.cpp) handles the rest.

**Preview before confirmation:** the user sees the normalized rule in plain language ("Agent X will not receive anything stating or strongly implying that you have cancer. Affected sentences are removed, the rest of each email stays visible.") and, once the build runs, a sample of before and after.

### 4.2 Dashboard

- List of rules with agent, plain-language description, status, coverage and pending-items count.
- Pause, resume, edit and delete.
- Manual editing of structured fields (agent, entities, treatment, `hold_until_ready`).
- A sample view of "what Agent X sees" for a given email.
- Notification when a rule moves from `building` to `active`, or to `needs_review` or `failed`.

### 4.3 Storage

PostgreSQL, `authz` schema:

| Table | Responsibility |
|---|---|
| `authz.policy` | Stable identity, owner, principal, status. |
| `authz.policy_revision` | Immutable PolicySpec versions. |
| `authz.policy_build` | Build status, coverage, classifier version, timestamps. |

Each change creates a new immutable revision. The original natural-language instruction may be retained encrypted for traceability and must not be exposed through MCP or ordinary logs.

---

## 5. Policy Engine

### 5.1 Responsibility

The Policy Engine decides **what scope applies to an agent for an action**. It is a plain Python evaluator over PolicySpecs. It is not OPA.

Rationale: Rosalind is single-tenant, the logic is set membership over entities, agents and rules, and the semantic part cannot be expressed in a policy language anyway. A compiler to Rego and partial evaluation to SQL would add a service and a second source of truth without removing real complexity. This can be revisited if Rosalind becomes multi-user.

### 5.2 Decision process

For each MCP request:

1. Authenticate the agent. The principal is the credential issued to the MCP client, not the model behind it.
2. Identify the requested action.
3. Load active policy revisions for that principal.
4. Evaluate grants and denies and resolve precedence.
5. Return an `EffectiveScope`.

```text
EffectiveScope
  decision: PERMIT | DENY
  agent_id: agent_x
  policy_version: 12
  exact_scope:
    permitted_entities: [...]
    permitted_accounts: [...]
    date_limits: [...]
  protected_information:
    - policy_id, statement_id, treatment, status (building|active), hold_until_ready
  scope_fingerprint: ...
```

The engine does not search, rank, embed, classify raw text, or return content.

---

## 6. Semantic Pipeline (fact-level protection)

This is the core of Tier-2 enforcement. It works asynchronously and produces what RAG Filtering needs.

### 6.1 Segmentation

Every text field (subject, body, quoted blocks, attachment text) is split into **segments** (sentence or clause level). The segment is the atomic unit of retrieval and filtering.

- Each segment has a stable content hash. The same sentence quoted in a reply inherits the same findings, so a protected sentence cannot leak through a quoted copy.
- Chunks used for context are assembled at query time from authorized segments.

### 6.2 Candidate generation

Running a local LLM over the whole archive for every new rule is too slow. A cheap, recall-oriented first stage narrows the set:

- Taxonomy tagging and Presidio-style recognizers (health, finance, identity, etc.).
- LLM-generated term and concept expansion from the protected statement.
- Low-threshold embedding similarity to the statement.

Taxonomy tags are used **only to find candidates**. They never block anything by themselves.

### 6.3 Verification

A local model judges each candidate segment against the protected statement:

- Verdict: `asserts`, `implies`, `evidence`, or `none`.
- The minimal sensitive span offsets inside the segment.
- Confidence and classifier version.

Thresholds are tuned for recall. Weak signals ("I hope you feel better") are the hard cases. Whether they are flagged is a utility versus leakage tradeoff measured by the evaluation set (section 11), not decided by hand.

**Prompt-injection hardening.** Emails are untrusted input to this model.

- Constrained output schema only (enum verdict plus offsets).
- Deterministic recognizers act as a floor. Model output can add findings but never remove a deterministic one.
- Segment text is passed as quoted data, never as instructions.
- Injection test cases are part of the evaluation set.

### 6.4 Provenance

```text
derived.span            segment_id, start, end, hash
derived.finding         span_id, statement_id, verdict, confidence, classifier_version
derived.fact            extracted facts, each linked to source spans
derived.fact_evidence   fact_id -> span_id
derived.fact_relation   links between facts
```

Any fact, summary or extraction derived from a hidden span is itself hidden for that agent. Sensitivity propagates through provenance.

### 6.5 Sanitized rendering

For an agent with an active rule, a flagged segment is rendered as follows:

1. Remove the protected span.
2. Apply a minimal rewrite so the remainder reads naturally.
3. Run a verifier pass confirming the result neither states nor implies the protected statement.
4. If verification fails, apply the fallback and drop the whole segment (not the email).
5. By default no marker is left ("[redacted]" would reveal that something is hidden).

Example:

| Original | Agent X sees |
|---|---|
| "I have cancer, let's meet tomorrow at 10am." | "Let's meet tomorrow at 10am." |
| "Your chemotherapy is scheduled for Thursday." | *(segment dropped; nothing safe remains)* |

### 6.6 Sanitized overlay index

Rendering sanitized text on output is not enough. If the search index is built on the original text, a query for "cancer" would still rank and return the sanitized segment, which tells the agent that the segment is about cancer. This is an oracle leak, through both BM25 and embeddings.

Design:

- The base index covers original segments.
- For each active semantic scope, the build creates `search.segment_view` rows for the affected segments only: `scope_fingerprint, segment_id, sanitized_text, bm25 entry, embedding`.
- For an agent, retrieval searches the base index **excluding affected segments**, plus that agent's overlay rows.

Overlays exist for a small fraction of segments, so storage and embedding cost stay modest. Overlays are keyed by scope fingerprint, so agents with the same rules share them. This design needs validation in the Phase 0 spike (section 14).

### 6.7 Asynchronous build and coverage

- On confirmation, the rule enters `building`. Candidate generation and verification run over the archive in the background.
- Coverage is reported as processed segments over total.
- When the backlog is clear, the rule becomes `active`.
- New and updated items go through the same pipeline incrementally. The dashboard shows a pending-items count.
- If a classifier version changes, affected findings are re-run and the version is recorded on every finding.

### 6.8 Metadata fields

Subject lines and attachment names are segmented and sanitized like body text. Sender and entity names can themselves reveal a protected fact (an oncology clinic). Treatment of such entities is an open decision (section 15). They are not blocked by default.

---

## 7. RAG Filtering

### 7.1 Responsibility

RAG Filtering applies the `EffectiveScope` and the semantic views to the actual data. It does not interpret policies.

### 7.2 Where filtering happens

**A. Retrieval**

- Exact-scope predicates (account, grants, participants, dates) are mandatory and cannot be overridden by user-requested filters.
- BM25 and vector retrieval run over base minus affected segments, plus the agent's overlay.
- Existing user-facing filters (sender, dates, tags, conversation) remain and combine with the mandatory scope by AND.

**B. Reranking**

Only authorized and sanitized candidates reach the reranker. The reranker must run locally.

**C. Context assembly**

- Render sanitized text only. Original text of an affected segment never leaves the retrieval layer.
- Deduplicate, including quoted copies by content hash.
- Provenance check: every returned item traces to authorized sources.
- **Final semantic gate:** a local check of the combined context for the protected statements. This is a safety net, not a guarantee. If the gate cannot establish safety, it drops the least-certain segments or abstains.

### 7.3 Database enforcement

- Mandatory SQL predicates generated from the `EffectiveScope`.
- The agent-facing read path uses a dedicated DB role limited to security-barrier views. Those views expose only authorized, sanitized text, never raw segment text of affected rows.
- PostgreSQL RLS for exact scoping (account and agent grants), as defence in depth. The retrieval service must not run under an owner or superuser role that bypasses RLS.
- **Filtered ANN:** HNSW with selective filters can return fewer than k results. Verify iterative-scan support in the pgvector version in use, or fall back to partitioning or a per-agent visibility table.

### 7.4 All MCP tools use the same layer

| MCP tool | Enforcement |
|---|---|
| `search` | Scope plus overlay, then sanitized results. |
| `get_item` | Authorize the item, render sanitized text. |
| `get_thread` | Sanitize each message. Gaps must not reveal removed content. |
| `get_context` | Sanitize each neighbouring item. |
| `list_extractions` | Hide facts derived from hidden spans. |
| `find_entity` | Restrict entities and handles that are access-restricted. |
| `describe_capabilities` | No restricted coverage or metadata. |

### 7.5 Side channels

- A sanitized segment must be indistinguishable from an unaffected one: no markers, same result formats.
- Counts, totals and pagination are computed over the agent-visible set only.
- Errors and empty results do not distinguish "nothing there" from "hidden".
- Cursors and caches are bound to `policy_version` and scope fingerprint.

---

## 8. Example: protecting a cancer diagnosis

The user creates the rule: *"Agent X should not know that I have cancer."* Agent X has been granted access to the mailbox.

| Email | Original | Agent X sees |
|---|---|---|
| E1 — Doctor | "Your chemotherapy is scheduled for Thursday." | Segment dropped. |
| E2 — Family | "How did your treatment go?" | Segment dropped (evidence). |
| E3 — Employer | "I hope you feel better. We can postpone the meeting." | Flagging the first sentence depends on thresholds. "We can postpone the meeting." is always kept. |
| E4 — User | "I will be unavailable every other Thursday for medical appointments." | Borderline. Weak evidence, decided by evaluation results. |
| E5 — User | "I have cancer, let's meet tomorrow at 10am." | "Let's meet tomorrow at 10am." |

Flow:

1. The interpreter produces a `confidentiality` PolicySpec. The user confirms the preview.
2. The rule enters `building`. The dashboard shows coverage. Agent X is not blocked in the meantime, and the user was told the rule is not yet enforced.
3. Candidate generation and verification flag spans. Sanitized overlay rows are created.
4. The rule becomes `active` and the user is notified.
5. Agent X's search for "chemotherapy" finds nothing from E1, because the original segment is excluded from its index. Its search for "meeting tomorrow" returns E5 in sanitized form.
6. The final gate inspects the assembled context for combinations that still imply the diagnosis.

---

## 9. Responsibilities

| Question | Policy Engine | Semantic Pipeline | RAG Filtering |
|---|---|---|---|
| Who is requesting? | Authenticates and resolves the principal. | — | Receives the resolved identity. |
| Which rules apply? | Evaluates grants, denies, precedence. | — | Does not reinterpret rules. |
| Which spans are protected? | Names the protected statements. | Finds and verifies the spans. | Applies the results. |
| What does the agent see of a flagged segment? | Specifies the treatment. | Builds sanitized text and overlay. | Serves only sanitized text. |
| Which emails match a contact? | Defines the condition. | — | Executes it. |
| Can combined content reveal a secret? | Supplies protected statements. | — | Final gate on assembled context. |
| Who generates SQL? | Produces `EffectiveScope`. | — | Compiles it into queries. |
| Who retrieves? | No. | No. | Yes. |

**Principle:** the Policy Engine decides what must be protected, the Semantic Pipeline finds it, and RAG Filtering ensures the agent only ever receives what remains.

---

## 10. Security and operational requirements

1. **Default deny for access.** No agent receives data without an applicable grant.
2. **Non-blocking confidentiality.** A rule that is not ready is never silently assumed active. The user is told. Strict holding is opt-in via `hold_until_ready`.
3. **Non-removable scope:** user-requested search filters cannot override authorization.
4. **Consistent enforcement:** every MCP tool uses the same layer.
5. **Policy versioning:** every request records the policy version and scope fingerprint it used.
6. **Auditing:** principal, action, policy version, decision, scope fingerprint. Never log content.
7. **Privacy-preserving errors and side channels** (section 7.5).
8. **Local processing:** interpretation, classification, verification and the final gate use local models only. Reranking is local.
9. **Derived-data protection:** sensitivity propagates through provenance to facts, summaries and extractions.
10. **Injection resistance** for every model that reads email text (section 6.3).
11. **Revocation and change:** cursors, caches and assembled contexts are invalidated when the policy version changes.
12. **Abuse limits:** per-agent rate limits and query-pattern anomaly flags. This is the realistic form of cross-query protection. It cannot prevent accumulation of permitted facts.

---

## 11. Evaluation

The semantic pipeline is the main technical risk, so it is measured from the start.

- **Synthetic mailboxes** with planted protected facts, direct, paraphrased, implied, quoted, cross-email and in attachments and subjects.
- **Metrics:**
  - Leak rate (protected spans reaching the agent): the headline security metric.
  - Over-redaction rate (non-protected content removed): the utility metric.
  - Rewrite leakage (sanitized text that still implies the fact).
  - Overlay oracle test: do search results or ranking reveal hidden content?
- **Adversarial agent:** scripted probing ("chemo", "hospital", "wig", "sick leave", "why unavailable Thursdays").
- **Injection cases** embedded in emails.
- **Regression gate:** a classifier or prompt change cannot ship if leak rate regresses.
- Evaluation results drive thresholds and what the dashboard can honestly say about coverage.

---

## 12. Known limitations

- Semantic protection is best-effort. Its recall is measured and bounded, not proven.
- An agent can combine permitted information with its own world knowledge or with other data. Rosalind controls only what it returns.
- In default (non-blocking) mode, there is an exposure window while a rule is building and while new items are pending. `hold_until_ready` closes it at the cost of availability.
- Revocation cannot un-disclose what an agent already received.
- Weak-evidence statements ("medical appointments") cannot be classified perfectly. Thresholds trade leakage against utility.

---

## 13. Technology stack

| Component | Technology |
|---|---|
| Canonical policy | Versioned PolicySpec JSON Schema, Pydantic validation |
| Persistence | PostgreSQL JSONB (`authz` schema) |
| Policy Engine | Python evaluator, no OPA |
| NL interpretation | Deterministic parsing plus local LLM (Ollama or llama.cpp) |
| Entity resolution | Existing Rosalind entity system |
| Segmentation | Sentence/clause splitter with stable hashing |
| Candidate generation | Presidio and custom recognizers, taxonomy tagging, embeddings, LLM term expansion |
| Verification | Local LLM or NLI model with constrained output |
| Sanitized views | `search.segment_view` overlay with BM25 and pgvector entries |
| Lexical retrieval | Existing BM25 / ParadeDB |
| Semantic retrieval | Existing pgvector / HNSW |
| DB enforcement | Dedicated agent-facing role, security-barrier views, RLS for exact scoping |
| Final gate | Local semantic check |
| Background jobs | Existing job system or a Postgres-backed queue |

---

## 14. Implementation roadmap

### Phase 0 — Evaluation harness and semantic spike

- Build the synthetic mailbox and the leak and over-redaction metrics.
- Prototype segmentation, candidate generation, verification and sanitized rewriting for one protected fact.
- Validate the overlay index design and filtered ANN behaviour.
- Output: measured recall and utility, and a go or adjust decision for Tier-2 scope.

### Phase 1 — Policy model and storage

- PolicySpec v2, `authz` tables, immutable revisions, status model.
- Manual creation and validation of JSON policies.

### Phase 2 — Policy Engine and exact scoping

- Python evaluator and `EffectiveScope`.
- Mandatory SQL predicates, RLS, agent-facing role and views.
- Apply to all MCP tools. Audit and versioning.

### Phase 3 — Semantic pipeline

- Segment store, span and finding tables, provenance.
- Async build with coverage and incremental processing.
- Status reporting.

### Phase 4 — Sanitized retrieval and context

- Overlay index, sanitized rendering and verifier.
- Context assembly, final gate and side-channel hardening.
- Cache and cursor invalidation.

### Phase 5 — Interpreter and dashboard

- Local intent classification, slot extraction, entity resolution.
- Preview and confirmation, dashboard, notifications.
- `hold_until_ready` option.

### Phase 6 — Hardening

- Red-team runs, injection suite, rate limits and anomaly flags.
- Classifier regression gate in CI.

---

## 15. Open decisions

1. **Marker or silent removal:** default is silent. A marker reveals that something exists.
2. **Entity and sender metadata:** pseudonymize entities that themselves reveal a protected fact (e.g. an oncology clinic), or accept the residual risk?
3. **Rewrite versus drop:** how aggressive the minimal rewrite should be before falling back to dropping the segment.
4. **Definition of "ready":** full backlog processed, or also an evaluation-based coverage threshold per rule.
5. **Weak evidence policy:** default thresholds, and whether the user can tune them per rule (e.g. "strict" and "relaxed").
6. **Overlay storage cost** at larger archive sizes, and whether overlays are shared across agents with identical scope.

---

## 16. References

- [NIST SP 800-162 — Guide to Attribute Based Access Control](https://csrc.nist.gov/pubs/sp/800/162/upd2/final) (conceptual background)
- [PostgreSQL — Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Microsoft Presidio](https://microsoft.github.io/presidio/)
- [pgvector](https://github.com/pgvector/pgvector)

**Final architectural principle:** Rosalind owns the policies and enforces them internally. The Policy Engine decides what an agent may know, the Semantic Pipeline finds the protected information down to the span, and RAG Filtering ensures the agent only ever receives the authorized, sanitized remainder, with the user always informed of how far each rule has progressed.
