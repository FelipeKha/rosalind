# Rosalind — Policy Engine & RAG Filtering (v4)

**Changes since v3**

- Every policy revision now stores the user's original prompt, the confirmed plain-language description and the interpreter version in a `source` block (section 3.5).
- The protected statement is now a separate, shared object (section 3.6).
- Added worked examples of constraint creation and request-time use for one semantic and one exact constraint (section 4.4).
- Deny rules on senders use a `sender_entity_id` predicate, and copies of denied text are masked by content hash (sections 4.4, 7.2).

**Earlier changes (v3)**

- Added when and where protected information is identified (section 6.5) and the per-stage enforcement view (section 7.2).
- Sanitization is now *cut at verifier offsets plus a visible, uniform redaction marker*. The LLM rewrite step is gone (section 6.6).
- Added full-item reads and the field-by-field rules (section 7.3).
- Added owner-facing transparency: audit, agent-view diff, spot-check queue (section 4.2).
- Agents and human readers see the same thing: redaction is visible. Probing protections are deferred to Phase 6.

---

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
- **Visibly redacted:** Agents see the same thing a human reader would: a marker where information was removed. The agent can tell its user that part of an item is hidden by the owner's privacy policy.
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
| Semantic protection | "Don't let Agent A know I have cancer" | Model-based, best-effort, measured by recall. |

The user does not choose between them. The interpreter routes each rule to the right mechanism. The dashboard shows how each rule is enforced. Semantic rules show a coverage figure and are labelled as AI-detected, not as guaranteed.

---

## 2. High-level architecture

```text
                  USER
                    |
                    | "Agent A should not know I have cancer"
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
+-----------------------+            | Findings + provenance     |
          |                          | Sanitized overlay         |
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
          | JIT verification of   |
          |   unprocessed segments|
          | Marker rendering      |
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
  "source": {
    "kind": "natural_language",
    "prompt": "Agent Y can see my emails with John Smith",
    "interpreter_version": "interp-2.1"
  },
  "status": "active"
}
```

The contact's name is resolved to a canonical Rosalind entity ID. If resolution is ambiguous (two "John Smith"), no grant is created and the policy waits in `needs_review`.

Deny rules use the same shape with `"effect": "deny"` (see the worked example in section 4.4).

Content-based grants ("my travel agent can access flight and hotel reservations") use the semantic pipeline to identify matching emails. They are allow-lists, so they fail safe: until the build is ready, the agent simply has no access through that grant.

### 3.2 Confidentiality policies (protected information)

Confidentiality policies specify information an agent must not learn. The protected item is a **statement about the world**, not a category label.

> Agent A should not know that I have cancer.

```json
{
  "schema_version": "rosalind.policy.v2",
  "type": "confidentiality",
  "effect": "deny",
  "principal": { "type": "agent", "id": "agent_a" },
  "actions": [
    "email.search",
    "email.read_content",
    "email.read_attachment",
    "email.read_extraction"
  ],
  "resource": {
    "type": "protected_information",
    "kind": "fact",
    "statement_id": "st_17",
    "match_levels": ["asserts", "implies", "evidence"]
  },
  "treatment": {
    "mode": "redact_span",
    "fallback": "drop_segment"
  },
  "enforcement": { "hold_until_ready": false },
  "source": {
    "kind": "natural_language",
    "prompt": "Agent A can't know I have cancer",
    "language": "en",
    "confirmed_description": "Agent A will not receive anything stating or strongly implying that you have cancer. Affected parts are replaced by a redaction marker.",
    "interpreter_version": "interp-2.1",
    "confirmed_at": "2026-11-18T10:42:00Z"
  },
  "status": "building"
}
```

| Field | Meaning |
|---|---|
| `statement_id` | Reference to the canonical protected statement (section 3.6). |
| `source` | The user's original instruction and how it was interpreted (section 3.5). Ignored by the evaluator. |
| `kind` | `fact` (a specific statement) or `topic` (e.g. "my financial information"). Both are enforced at span level, never by blocking whole emails. |
| `match_levels` | `asserts`: states or paraphrases it. `implies`: entails it ("my oncologist said the scan is clear"). `evidence`: strongly suggestive ("chemotherapy on Thursday"). Weak or ambiguous evidence is handled by classifier thresholds and the final gate (see section 6.3). |
| `treatment.mode` | `redact_span` replaces only the protected span with the redaction marker. `drop_segment` replaces the whole sentence or clause with the marker. |
| `treatment.fallback` | Used when the result of a span redaction fails verification (section 6.6). The fallback is the smallest enclosing segment, never the whole email. |
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

### 3.5 Source of a policy (the user's prompt)

Every policy revision carries a `source` block. It is persisted with the revision but is not evaluated.

```json
"source": {
  "kind": "natural_language",
  "prompt": "Agent A can't know I have cancer",
  "language": "en",
  "confirmed_description": "Agent A will not receive anything stating or strongly implying that you have cancer. Affected parts are replaced by a redaction marker.",
  "interpreter_version": "interp-2.1",
  "confirmed_at": "2026-11-18T10:42:00Z"
}
```

| Field | Meaning |
|---|---|
| `kind` | `natural_language` (created from a prompt) or `dashboard_edit` (created by manual editing). A dashboard edit stores no new prompt and records which fields changed. |
| `prompt` | The user's text, verbatim. |
| `confirmed_description` | The plain-language preview the user actually confirmed. |
| `interpreter_version` | The interpreter that produced the spec. |

Uses:

- **Dashboard:** show "You said: ..." next to the interpreted rule, with the revision history.
- **Traceability and disputes:** compare what the user wrote, what they confirmed and what the spec does.
- **Re-interpretation:** when the interpreter improves, the stored prompt can be re-run. The result is a new *draft* revision for the user to confirm, never applied automatically.
- **Debugging** misinterpretations.

Handling:

- The prompt is itself sensitive ("I have cancer"). It is encrypted at rest and readable only in the owner dashboard.
- It never appears in MCP responses, audit entries, ordinary logs, external model calls or the semantic pipeline.
- Nothing is persisted before the user confirms the preview. Drafts are ephemeral.
- Each revision has its own `source`. The original prompt stays on revision 1 and remains visible in the revision history.

### 3.6 Protected statement object

The statement is stored separately from the policy, so several policies (or agents) can share it and its findings.

```json
{
  "statement_id": "st_17",
  "canonical": "The user has cancer",
  "subject": "person_self",
  "embedding": "[...]",
  "expansion": { "terms": ["chemotherapy", "oncologist", "tumor", "biopsy", "diagnosis"] },
  "version": 1
}
```

- The statement is the normalized form of the prompt. First-person text is resolved ("I" becomes `person_self`), because verifiers can't use it.
- Creation embeds the new statement and compares it with existing ones. A match reuses the existing `statement_id` and all its findings.
- The expansion terms feed candidate generation only. They block nothing.
- The statement is the secret in a different form, so it gets the same encryption and access restrictions as `source.prompt`.

---

## 4. Policy creation, storage and dashboard

Users create policies through a natural-language box.

- "Agent A should not know that I have cancer."
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
Storage (revision with source prompt), then async build
```

The interpreter has access to registered agents, the entity directory and the PolicySpec schema. It does not need access to the email archive. It never produces SQL or executable policy code, only a validated PolicySpec.

Deterministic parsing handles common phrasings. A local LLM (Ollama or llama.cpp) handles the rest.

**Preview before confirmation:** the user sees the normalized rule in plain language ("Agent A will not receive anything stating or strongly implying that you have cancer. Affected sentences are replaced by a redaction marker, the rest of each email stays visible.") and, once the build runs, a sample of before and after.

**On confirmation**, the revision is saved together with the user's verbatim prompt and the confirmed description (section 3.5). Before confirmation nothing is persisted.

### 4.2 Dashboard and owner transparency

The owner is the one person who can safely see what was removed.

- **Rules:** list with agent, plain-language description, status, coverage and pending-items count. Pause, resume, edit, delete. Manual editing of structured fields (agent, entities, treatment, `hold_until_ready`).
- **Original instruction:** each rule shows what the user wrote next to how it was interpreted, with the revision history.
- **Notifications:** when a rule moves from `building` to `active`, or to `needs_review` or `failed`.
- **Per-request audit:** "Agent A read email X, 1 segment redacted under rule R12." The log stores segment IDs and hashes, never content.
- **Agent-view diff:** original versus what Agent A saw, re-rendered on demand from stored data, for any item and request.
- **Per-rule stats:** segments affected, requests served with redactions.
- **Spot-check queue:** the audit shows what was removed but never what was *missed*. The dashboard surfaces low-confidence verifier calls and random samples of unflagged candidate segments for the user to review. This is how false negatives get caught.

### 4.3 Storage

PostgreSQL:

| Table | Responsibility |
|---|---|
| `authz.policy` | Stable identity, owner, principal, status. |
| `authz.policy_revision` | Immutable PolicySpec versions, including the `source` block (user's original prompt, encrypted). |
| `authz.policy_build` | Build status, coverage, classifier version, timestamps. |
| `semantic.protected_statement` | Canonical protected statements shared across policies (section 3.6). Encrypted and access-restricted. |
| `audit.request_log` | Principal, action, policy version, scope fingerprint, item IDs, decision. |
| `audit.redaction_event` | Request, segment ID and hash, rule, treatment. No content. |

Each change creates a new immutable revision. The `source.prompt` is encrypted at rest and readable only in the owner dashboard. It is never exposed through MCP, ordinary logs, audit entries, external models or the semantic pipeline (section 3.5).

### 4.4 Constraint creation: worked examples

Two constraints for Agent A, illustrated with the email E5: "I have cancer, let's meet tomorrow at 10am."

#### Constraint 1: "Agent A can't know I have cancer" (semantic)

**Persisted objects**

1. The policy revision from section 3.2, including its `source` block with the user's prompt.
2. The protected statement `st_17` from section 3.6.
3. A build record in `authz.policy_build`: status `building`, coverage 0 of N segments, classifier version.

**At creation**

1. **Interpret.** The local interpreter resolves "I" to the user's own entity and normalizes the statement to "The user has cancer".
2. **Deduplicate the statement.** It is embedded and compared with existing statements. A match reuses the existing `statement_id` and its findings.
3. **Expand.** A local LLM generates related terms and concepts, used for candidate generation only.
4. **Preview and confirm.** The user sees: "Agent A will not receive anything stating or strongly implying that you have cancer. Affected parts are replaced by a redaction marker." On confirmation the revision is saved with the verbatim prompt and that description in `source`.
5. **Build, asynchronously.** For each segment: candidate generation, local verification, findings and overlay rows. The dashboard shows coverage.

For E5 the build produces:

```text
derived.finding:  segment_hash 9f3a…, statement st_17, verdict asserts,
                  span [0,14] "I have cancer,", raw_score 0.98, classifier v3
search.segment_view (scope_fingerprint sf_a_1):
  display_text: "[REDACTED BY PRIVACY POLICY], let's meet tomorrow at 10am."
  index_text:   "let's meet tomorrow at 10am."
  + BM25 and embedding entries computed on index_text
```

Before the overlay row is saved, the safety check (the sanitized text doesn't imply the statement) and the utility check ("tomorrow" and "10am" still extractable) must pass. If either fails, the treatment falls back to `drop_segment`.

When coverage reaches 100% the status becomes `active` and the user is notified. New emails go through the same pipeline incrementally.

**At request time** (Agent A asks "when is the meeting?")

1. The Policy Engine returns the `EffectiveScope`: exact scope, `protected_information: [{ st_17, redact_span, active }]`, `scope_fingerprint: sf_a_1`.
2. Retrieval searches two sets together: base segments in exact scope with no finding for `st_17` above threshold, plus overlay rows for `sf_a_1` (searched on `index_text`). E5's segment is excluded from the first set and found in the second. A search for "cancer" matches nothing.
3. Reranking runs locally on sanitized candidates only.
4. JIT verification covers any returned segment with no finding for `st_17` yet.
5. Assembly returns `display_text` plus the `redactions` field. The final gate checks the combined context.

If the rule is still `building`, retrieval can only exclude segments that already have findings. The rest are served as-is, except for JIT on the returned segments, and the audit records the pending ones.

#### Constraint 2: "Agent A can't see emails from John Smith" (exact)

**Persisted object**

One policy revision. There is no statement and no build, because nothing semantic is involved.

```json
{
  "policy_id": "pol_42", "revision": 1,
  "schema_version": "rosalind.policy.v2",
  "type": "access",
  "effect": "deny",
  "principal": { "type": "agent", "id": "agent_a" },
  "actions": ["email.search", "email.read_content",
              "email.read_attachment", "email.read_extraction"],
  "resource": {
    "type": "email",
    "selector": {
      "operator": "has_participant",
      "entity_id": "person_123",
      "roles": ["from"]
    }
  },
  "source": {
    "kind": "natural_language",
    "prompt": "Agent A can't see emails from John Smith",
    "language": "en",
    "confirmed_description": "Agent A will not see the 312 emails sent by John Smith (2 addresses).",
    "interpreter_version": "interp-2.1",
    "confirmed_at": "2026-11-18T10:51:00Z"
  },
  "status": "active"
}
```

The rule stores the **entity ID, not email addresses**. If John gets a new address or two contacts are merged, the rule follows.

**At creation**

1. **Interpret.** "Emails from" maps to role `from` only. Emails where John is cc'd are unaffected unless the user says so.
2. **Resolve the entity.** If there are two John Smiths, the policy stays `needs_review` and asks the user which one. No rule is created from a guess.
3. **Preview and confirm.** The preview shows the affected count. On confirmation the revision is saved with the prompt.
4. **No build.** Every email already has a `sender_entity_id` from ingestion, so the rule is `active` immediately.

**At request time**

The `EffectiveScope` carries `denied_selectors: [{ sender_entity_id: person_123 }]`. Retrieval turns it into a mandatory predicate on BM25 and vector queries, for base and overlay rows:

```text
AND NOT (sender_entity_id = ANY(:denied_sender_entities))
```

RLS repeats it as defence in depth. **Exact predicates run first, then the semantic anti-join and overlay.** An email from John that says "I have cancer, let's meet" is excluded by the deny, so semantic handling never sees it.

| Request | Behaviour |
|---|---|
| `search` | John's emails never appear. Counts and pagination exclude them. |
| `get_item` on John's email ID | Identical to "not found". |
| `get_thread` containing John's messages | Placeholder with the redaction marker, no sender, date or size. |
| Attachments and extractions from John's emails | Hidden with the email. |
| Quoted copies of John's text in other emails | Segments whose content hash matches a segment of a denied email are replaced by the marker (best-effort, open decision 8). |
| `find_entity("John Smith")` | Still returns him by default (open decision 7). |

#### Side by side

| | Constraint 1 | Constraint 2 |
|---|---|---|
| Kind | Semantic, best-effort | Exact, deterministic |
| Persisted | Policy revision with source prompt, protected statement, build record, findings, overlay rows | Policy revision with source prompt |
| Creation work | Interpret, deduplicate statement, expand, confirm, async build | Interpret, resolve entity, preview, confirm |
| Ready when | Backlog processed (`building` to `active`) | Immediately |
| Unit affected | Segment (span within it) | Whole email |
| Request-time mechanism | Anti-join on findings, overlay, JIT, final gate | SQL predicate on `sender_entity_id`, RLS, hash masking |
| If unresolved | Not enforced, user notified | No rule created (`needs_review`) |

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
  agent_id: agent_a
  policy_version: 12
  exact_scope:
    permitted_entities: [...]
    permitted_accounts: [...]
    date_limits: [...]
    denied_selectors: [{ sender_entity_id: person_123 }]
  protected_information:
    - policy_id, statement_id, treatment, status (building|active), hold_until_ready
  scope_fingerprint: ...
```

The engine does not search, rank, embed, classify raw text, or return content.

---

## 6. Semantic Pipeline (fact-level protection)

This is the core of semantic enforcement. It works asynchronously and produces what RAG Filtering needs.

### 6.1 Segmentation

Every text field (subject, body, quoted blocks, attachment text) is split into **segments** (sentence or clause level). The segment is the atomic unit of retrieval and filtering.

- Each segment has a stable content hash. The same sentence quoted in a reply inherits the same findings, so a protected sentence cannot leak through a quoted copy.
- Chunks used for context are assembled at query time from authorized segments.
- Segment boundaries do not need to be perfect. The verifier returns character offsets, so a comma-spliced sentence like "I have cancer, let's meet tomorrow at 10am" is cut inside the segment.

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
- Raw confidence score and classifier version.

Thresholds are tuned for recall. Weak signals ("I hope you feel better") are the hard cases. Whether they are flagged is a utility versus leakage tradeoff measured by the evaluation set (section 11), not decided by hand.

**Prompt-injection hardening.** Emails are untrusted input to this model.

- Constrained output schema only (enum verdict plus offsets).
- Deterministic recognizers act as a floor. Model output can add findings but never remove a deterministic one.
- Segment text is passed as quoted data, never as instructions.
- Injection test cases are part of the evaluation set.

### 6.4 Findings and provenance

A finding belongs to the **segment**, not to the agent: "segment X asserts statement S1", stored once, keyed by segment content hash and normalized statement. The agent enters only at enforcement time.

```text
derived.span            segment_id, start, end, hash
derived.finding         span_id, statement_id, verdict, raw_score, classifier_version
derived.fact            extracted facts, each linked to source spans
derived.fact_evidence   fact_id -> span_id
derived.fact_relation   links between facts
```

Consequences:

- A second agent with the same rule ("Agent B can't know I have cancer") needs no re-verification. It points to the same findings and the same overlay.
- Raw scores are stored, so changing a confidence threshold means rebuilding overlays, not re-running the model.
- Extracted facts point at **span offsets**, not whole segments. The event "Meeting, tomorrow 10:00" has its evidence in the unprotected span and stays visible. A fact extracted from "I have cancer" is hidden. Sensitivity propagates through provenance to facts, summaries and extractions.

### 6.5 When protected information is identified

Identification is offline and runs once per segment and statement. Query time reads the result.

| Moment | What happens |
|---|---|
| **Rule creation** | The statement is registered and the backfill starts: candidate generation, verification, findings, sanitized overlay rows. The rule is `building` until the backlog is clear. |
| **New or updated email** | The same pipeline runs incrementally against every active statement. |
| **Classifier version change** | Affected findings are re-run in the background. The version is recorded on every finding. |
| **Query time: retrieval** | Lookup of stored findings. The original affected segment is excluded and the overlay row is used. No classification happens. |
| **Query time: JIT verification** | Any segment about to be returned that has no finding yet is verified synchronously. For `search` this covers the top-k results. For `get_item` it covers every segment of the item. |
| **Query time: final gate** | Cross-segment check of the assembled context. |

Why not query time only:

- **Ranking leak:** retrieving first and redacting after means a search for "cancer" ranks the meeting email high. Replacement must happen before ranking, which needs precomputed findings.
- **Cost and latency:** an LLM call per candidate segment per request.
- **Consistency:** the same sentence could be judged differently on different calls.

Why not offline only:

- New items and the build window have unprocessed segments (the JIT step covers this).
- Cross-segment inference only exists at assembly time.
- An offline miss would otherwise never get a second look.

JIT verification is bounded by a per-request time budget. If it can't finish, behaviour follows `hold_until_ready` (default: return as-is and record the segments as pending in the audit; strict: return the redaction marker). JIT results are persisted so later reads are identical.

### 6.6 Sanitization: cut and mark

For an agent with an active rule, a flagged segment is rendered in advance (at build time or JIT), not at query time.

1. **Cut:** remove the verifier's protected span by character offsets.
2. **Mark:** insert the uniform redaction marker `[REDACTED BY PRIVACY POLICY]` where the span was. Adjacent redacted spans merge into one marker.
3. **Verify safety:** a verifier pass confirms the result neither states nor implies the protected statement.
4. **Verify utility:** date, time and entity extractors run on the original-minus-span and on the sanitized text. They must find the same things.
5. **Fallback:** if either verification fails, the treatment falls back to `drop_segment`: the whole segment becomes one marker, never the whole email.
6. **Store** the overlay row with two texts: `display_text` (with marker) and `index_text` (without marker).

There is no LLM rewrite. Cutting plus a fixed token is deterministic and auditable.

| Case | Original | Agent A sees |
|---|---|---|
| Separable clause | "I have cancer, let's meet tomorrow at 10am." | "[REDACTED BY PRIVACY POLICY], let's meet tomorrow at 10am." |
| Entangled | "Chemo ends at 9, so let's meet at 10am." | "[REDACTED BY PRIVACY POLICY], so let's meet at 10am." (if verification fails, the whole segment becomes the marker) |
| Not separable | "I can't do mornings because of the cancer, so 10am." | "[REDACTED BY PRIVACY POLICY]" The 10am is lost. |

The third case is the real cost of fact-level filtering: information welded to the protected fact is lost. The evaluation set measures how often it happens.

**Marker rules**

- The marker is identical for every rule, agent and span length. It never names the rule, statement, category or policy ID.
- The marker is **not indexed**. BM25 and embeddings use `index_text`, so searching "redacted" does not surface affected segments.
- Responses also carry a machine-readable field so agents don't parse text:
  `"redactions": [{ "segment": 0, "type": "privacy_policy" }]`
- The MCP tool descriptions state that content may be redacted under the owner's privacy policy.

The marker tells the agent that something sensitive exists at that position and that a rule is probably in force. The agent can say so honestly to its user. Probing through repeated fetches is deferred to Phase 6 (section 12).

### 6.7 Sanitized overlay index

If the search index were built on original text, a query for "cancer" would still rank the sanitized segment, which tells the agent what the segment is about. This is an oracle leak, through both BM25 and embeddings.

Design:

- The base index covers original segments.
- For each active semantic scope, the build creates `search.segment_view` rows for the affected segments only: `scope_fingerprint, segment_id, display_text, index_text, bm25 entry, embedding`.
- For an agent, retrieval searches the base index **excluding affected segments**, plus that agent's overlay rows.

Overlays exist for a small fraction of segments, so storage and embedding cost stay modest. Overlays are keyed by scope fingerprint, so agents with the same rules share them. This design needs validation in the Phase 0 spike (section 14).

### 6.8 Asynchronous build and coverage

- On confirmation, the rule enters `building`.
- Coverage is reported as processed segments over total.
- When the backlog is clear, the rule becomes `active`.
- New and updated items go through the same pipeline incrementally. The dashboard shows a pending-items count.

### 6.9 Metadata fields

Subject lines and attachment names are segmented and sanitized like body text. Sender and entity names can themselves reveal a protected fact (an oncology clinic). Treatment of such entities is an open decision (section 15). They are not blocked by default.

---

## 7. RAG Filtering

### 7.1 Responsibility

RAG Filtering applies the `EffectiveScope` and the sanitized views to the actual data. It does not interpret policies.

### 7.2 Where each stage acts

| Stage | What happens |
|---|---|
| **Retrieval** | Mandatory exact-scope predicates (account, grants, denied selectors such as `sender_entity_id`, participants, dates), which user-requested filters can only narrow and which run before any semantic step. BM25 and vector search run over base minus affected segments, plus the agent's overlay. Segments whose content hash matches a segment of a denied email are replaced by the marker. |
| **Reranking** | Only authorized, sanitized candidates reach the reranker. It must run locally. |
| **Pre-assembly** | JIT verification of segments with no finding yet. |
| **Assembly** | Render `display_text`, deduplicate (quoted copies by content hash), provenance check that every returned item traces to authorized sources. |
| **Final gate** | Local check of the combined context for the protected statements. A safety net, not a guarantee. If it can't establish safety, it replaces the least-certain segments with the marker. |

### 7.3 Reading a full item (`get_item`)

An agent that gets a source email ID from a search result can request the full email. This goes through the same sanitized path as search. There is no raw-email route for agents.

1. **Authorize.** The Policy Engine confirms a grant covers the item. If not, the response is identical to "not found".
2. **Load segments, not the raw body.** The agent-facing DB role has no access to the raw body column. It reads through a view that maps each segment to original text (unaffected), overlay `display_text` (affected), or the marker (dropped).
3. **Complete JIT verification** for every segment of the item.
4. **Reassemble** in order, preserving paragraph structure.
5. **Final gate** on the whole item, since this is the highest-context request.
6. **Return** with the `redactions` field.

Consistency: the sanitized text returned by search and by `get_item` must be byte-identical. Both read the same stored overlay row, keyed by scope fingerprint and policy version, and nothing is regenerated per request.

| Field | Rule |
|---|---|
| Subject, preview, snippet | Segmented and sanitized like body text. |
| Quoted blocks | Same content hash, same findings. |
| HTML body, raw MIME / `.eml` | Not available to agents, or generated from sanitized segments only. |
| Highlight offsets, content length, size | Computed on the sanitized text. |
| Attachments | Names sanitized. Text extracted, segmented and treated like the body. Calendar invites included. |
| Extractions, linked entities | Filtered by span provenance. |
| Thread and reply-to links | Referenced by ID only. Each item goes through the same enforcement when fetched. |
| Email IDs | Opaque, never derived from content. |
| Fully redacted item | Returned as the item shell (sanitized metadata) with markers, not as "not found". |

### 7.4 Database enforcement

- Mandatory SQL predicates generated from the `EffectiveScope`.
- The agent-facing read path uses a dedicated DB role limited to security-barrier views. Those views expose only authorized, sanitized text, never raw segment text of affected rows.
- PostgreSQL RLS for exact scoping (account and agent grants), as defence in depth. The retrieval service must not run under an owner or superuser role that bypasses RLS.
- **Filtered ANN:** HNSW with selective filters can return fewer than k results. Verify iterative-scan support in the pgvector version in use, or fall back to partitioning or a per-agent visibility table.

### 7.5 All MCP tools use the same layer

| MCP tool | Enforcement |
|---|---|
| `search` | Scope plus overlay, JIT on top-k, sanitized results. |
| `get_item` | Section 7.3. |
| `get_thread` | Sanitize each message. Messages from denied senders appear as a placeholder with the redaction marker, with no sender, date or size. |
| `get_context` | Sanitize each neighbouring item. |
| `list_extractions` | Hide facts derived from hidden spans. |
| `find_entity` | Entities stay findable by default even when their emails are denied (open decision 7). |
| `describe_capabilities` | No restricted coverage or metadata. |

### 7.6 Side channels

- The marker is the only signal that content was removed, and it is identical everywhere.
- Counts, totals and pagination are computed over the agent-visible set only.
- Errors and empty results do not distinguish "nothing there" from "not permitted".
- Cursors and caches are bound to `policy_version` and scope fingerprint.

---

## 8. Example: protecting a cancer diagnosis

The user creates the rule: *"Agent A should not know that I have cancer."* Agent A has been granted access to the mailbox.

| Email | Original | Agent A sees |
|---|---|---|
| E1 — Doctor | "Your chemotherapy is scheduled for Thursday." | "[REDACTED BY PRIVACY POLICY]" |
| E2 — Family | "How did your treatment go?" | "[REDACTED BY PRIVACY POLICY]" (evidence) |
| E3 — Employer | "I hope you feel better. We can postpone the meeting." | Flagging the first sentence depends on thresholds. "We can postpone the meeting." is kept. |
| E4 — User | "I will be unavailable every other Thursday for medical appointments." | Borderline. Weak evidence, decided by evaluation results. |
| E5 — User | "I have cancer, let's meet tomorrow at 10am." | "[REDACTED BY PRIVACY POLICY], let's meet tomorrow at 10am." |

Flow:

1. The interpreter produces a `confidentiality` PolicySpec. The user confirms the preview, and the prompt is saved in the revision's `source` block.
2. The rule enters `building`. The dashboard shows coverage. Agent A is not blocked in the meantime, and the user was told the rule is not yet enforced.
3. Candidate generation and verification flag spans. Findings and overlay rows are created.
4. The rule becomes `active` and the user is notified.
5. Agent A asks "when is the meeting?". Retrieval uses the overlay for E5, so the result is `[REDACTED BY PRIVACY POLICY], let's meet tomorrow at 10am.` with the source email ID.
6. Agent A requests the full email. `get_item` returns the same sanitized text for that segment, plus the rest of the email, byte-identical to what search returned.
7. Agent A's search for "chemotherapy" returns nothing from E1, because the original segment is excluded from its index.
8. The owner sees in the audit: "Agent A read E5, 1 segment redacted under rule R12", and can open the agent-view diff.

---

## 9. Responsibilities

| Question | Policy Engine | Semantic Pipeline | RAG Filtering |
|---|---|---|---|
| Who is requesting? | Authenticates and resolves the principal. | — | Receives the resolved identity. |
| Which rules apply? | Evaluates grants, denies, precedence. | — | Does not reinterpret rules. |
| Which spans are protected? | Names the protected statements. | Finds and verifies the spans. | Applies the results. |
| What does the agent see of a flagged segment? | Specifies the treatment. | Builds sanitized text and overlay. | Serves only sanitized text. |
| Segments with no finding yet? | — | Verifies them (JIT). | Calls the pipeline before returning. |
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
4. **Consistent enforcement:** every MCP tool uses the same layer. No raw-content route for agents.
5. **Policy versioning:** every request records the policy version and scope fingerprint it used.
6. **Auditing:** principal, action, policy version, decision, scope fingerprint, redacted segment IDs and hashes. Never log content.
7. **Uniform markers and side-channel hardening** (sections 6.6 and 7.6).
8. **Local processing:** interpretation, classification, verification and the final gate use local models only. Reranking is local.
9. **Derived-data protection:** sensitivity propagates through provenance to facts, summaries and extractions.
10. **Injection resistance** for every model that reads email text (section 6.3).
11. **Revocation and change:** cursors, caches and assembled contexts are invalidated when the policy version changes.
12. **Abuse limits:** per-agent rate limits and query-pattern anomaly flags, to be extended in Phase 6.
13. **Protection of stored instructions and statements:** source prompts and protected statements are themselves sensitive. They are encrypted at rest, readable only in the owner dashboard, and excluded from MCP, logs, audit and external models.

---

## 11. Evaluation

The semantic pipeline is the main technical risk, so it is measured from the start.

- **Synthetic mailboxes** with planted protected facts: direct, paraphrased, implied, quoted, cross-email, and in attachments and subjects.
- **Metrics:**
  - Leak rate (protected spans reaching the agent): the headline security metric.
  - Over-redaction rate (non-protected content removed): the utility metric.
  - Residual leakage in sanitized text (text that still implies the fact).
  - Utility retention: non-protected facts (dates, times, entities) survive redaction.
  - Overlay oracle test: search results and ranking must not reveal hidden content.
  - Consistency test: search and `get_item` return byte-identical sanitized text.
  - Deny coverage: emails from a denied entity never appear in search, items, threads, counts or extractions, including copies matched by content hash.
- **Adversarial agent:** scripted probing ("chemo", "hospital", "wig", "sick leave", "why unavailable Thursdays"), including inference from marker positions.
- **Injection cases** embedded in emails.
- **Regression gate:** a classifier or prompt change cannot ship if leak rate regresses.
- Evaluation results drive thresholds and what the dashboard can honestly say about coverage.

---

## 12. Known limitations

- Semantic protection is best-effort. Its recall is measured and bounded, not proven.
- The marker reveals that something sensitive exists at a position, and that a rule is probably in force. Probing by fetching many items and inferring from marker positions and surrounding context is **not mitigated in v1**. Protections are on the Phase 6 backlog.
- An agent can combine permitted information with its own world knowledge or with other data. Rosalind controls only what it returns.
- In default (non-blocking) mode, there is an exposure window while a rule is building and while new items are pending. `hold_until_ready` closes it at the cost of availability.
- Information welded to a protected fact is lost with it (section 6.6, third case).
- Copies of a denied email's text inside other emails are masked by content-hash match. Reformatted quotes are not caught.
- Revocation cannot un-disclose what an agent already received.
- Weak-evidence statements ("medical appointments") cannot be classified perfectly. Thresholds trade leakage against utility.

---

## 13. Technology stack

| Component | Technology |
|---|---|
| Canonical policy | Versioned PolicySpec JSON Schema, Pydantic validation |
| Persistence | PostgreSQL JSONB (`authz` and `audit` schemas) |
| Policy Engine | Python evaluator, no OPA |
| NL interpretation | Deterministic parsing plus local LLM (Ollama or llama.cpp) |
| Entity resolution | Existing Rosalind entity system |
| Segmentation | Sentence/clause splitter with stable hashing |
| Candidate generation | Presidio and custom recognizers, taxonomy tagging, embeddings, LLM term expansion |
| Verification | Local LLM or NLI model with constrained output |
| Sanitization | Deterministic cut plus fixed marker, extractor-based utility check |
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
- Prototype segmentation, candidate generation, verification, and cut-plus-marker sanitization for one protected fact.
- Validate the overlay index design, the utility check, and filtered ANN behaviour.
- Output: measured recall and utility, and a go or adjust decision for semantic scope.

### Phase 1 — Policy model and storage

- PolicySpec v2, `authz` and `audit` tables, immutable revisions, status model.
- Encrypted `source` block (user prompt, confirmed description, interpreter version) and the `protected_statement` table.
- Manual creation and validation of JSON policies.

### Phase 2 — Policy Engine and exact scoping

- Python evaluator and `EffectiveScope`.
- Mandatory SQL predicates, RLS, agent-facing role and views.
- Denied selectors (`sender_entity_id`) and content-hash masking of quoted copies.
- Apply to all MCP tools. Audit and versioning.

### Phase 3 — Semantic pipeline

- Segment store, span and finding tables, provenance.
- Async build with coverage and incremental processing.
- Status reporting.

### Phase 4 — Sanitized retrieval and context

- Overlay index, marker rendering, safety and utility verification.
- JIT verification, full-item reads, context assembly, final gate.
- Cache and cursor invalidation.

### Phase 5 — Interpreter and dashboard

- Local intent classification, slot extraction, entity resolution.
- Preview and confirmation, dashboard, notifications.
- Audit views, agent-view diff, per-rule stats, spot-check queue.
- `hold_until_ready` option.

### Phase 6 — Hardening

- Red-team runs, injection suite, classifier regression gate in CI.
- Probing protections: query-pattern analysis, limits on marker-position inference, tighter rate limits.

---

## 15. Open decisions

1. **Sender and entity metadata:** pseudonymize entities that themselves reveal a protected fact (e.g. an oncology clinic), or accept the residual risk?
2. **Unverifiable attachments:** images and scans without usable OCR can't be checked. Options: return only name and type, or return the content and flag it in the dashboard.
3. **Definition of "ready":** full backlog processed, or also an evaluation-based coverage threshold per rule.
4. **Weak-evidence thresholds:** defaults, and whether the user can tune them per rule ("strict" and "relaxed").
5. **JIT time budget:** the value, and the behaviour when it is exceeded in default mode.
6. **Overlay storage cost** at larger archive sizes, and whether overlays are shared across agents with identical scope.
7. **Entity visibility under a deny:** by default the entity stays findable (`find_entity`) even when its emails are denied. Confirm, or let the user choose per rule.
8. **Copies of denied content:** default is best-effort masking by content-hash match. Confirm, or restrict to the exact-scope deny only.
9. **Retention of source prompts:** purge with the policy when it is deleted (default), or keep an encrypted history.

---

## 16. References

- [NIST SP 800-162 — Guide to Attribute Based Access Control](https://csrc.nist.gov/pubs/sp/800/162/upd2/final) (conceptual background)
- [PostgreSQL — Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Microsoft Presidio](https://microsoft.github.io/presidio/)
- [pgvector](https://github.com/pgvector/pgvector)

**Final architectural principle:** Rosalind owns the policies and enforces them internally. The Policy Engine decides what an agent may know, the Semantic Pipeline finds the protected information down to the span, and RAG Filtering ensures the agent only ever receives the authorized, visibly redacted remainder, with the owner always informed of how far each rule has progressed and what was hidden.
