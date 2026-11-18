# Rosalind — Policy Interpreter (Implementation Step 1)

Companion to `rosalind_policy_engine_rag_filtering_v5.md`. This document specifies how a user's natural-language instruction becomes a validated, confirmed and persisted policy object. It is the first implementation step.

---

## 1. Purpose and scope

**Input:** a prompt typed by the owner in the dashboard, such as "Agent A can't know I have cancer".

**Output:** one or more confirmed `PolicySpec` revisions, persisted with a `source` block (section 3.5 of the main document), plus protected-statement records for semantic rules.

**Principles**

1. **The LLM proposes, code decides.** The local LLM only extracts what the user said as raw text mentions. IDs, defaults, the spec and the preview text are produced by deterministic code.
2. **Nothing is persisted before the user confirms.** Drafts are ephemeral.
3. **Everything runs locally.** The prompt and every intermediate artifact are sensitive.
4. **The preview is rendered from the spec by templates**, never written by the LLM. What the user confirms is exactly what the system will enforce.
5. **Never guess.** Ambiguity produces a question or a `needs_review` state, not a best guess.

**In scope**

- Segmenting, routing, extracting, resolving, validating, previewing, confirming and persisting.
- Clarification questions and conflict detection.
- A minimal UI for the flow: prompt input, clarification options, preview, confirm.
- The tables needed to persist confirmed policies, and the golden-set evaluation.

**Out of scope for this step**

- Enforcement (Policy Engine, RAG filtering), the semantic pipeline and the full dashboard. They ship in later steps (section 14 of the main document).
- Natural-language edits or revocations of existing policies. In this step they are done in the dashboard.
- Content-based grants ("my travel agent can access flight reservations"). They need the semantic pipeline.

> **Important:** until enforcement ships, confirmed policies are recorded but not enforced. The preview says so (section 5.8), and no real agent traffic should be served under these policies yet.

---

## 2. Dependencies

The interpreter needs three things from the rest of Rosalind. They are assumed to exist and should be verified before implementation starts.

| Dependency | Needed for | Interface (to confirm) |
|---|---|---|
| Agent registry | Resolving "Agent A" | `list_agents()` returning id, display name, aliases, status |
| Entity directory | Resolving people and accounts | `search(query)` returning id, display name, aliases, addresses, email counts |
| Read-only count service | Impact counts in the preview | Returns integers only, over email metadata. Never content. |

The interpreter does not read email content.

---

## 3. Pipeline overview

```text
Prompt
  |
  v
[1] Segment into atomic constraints          code + LLM
  |
  v
[2] Route: access (exact) or confidentiality (semantic)   rules, LLM as tiebreaker
  |
  v
[3] Extract mentions into a ConstraintDraft  LLM, constrained JSON, no IDs
  |
  v
[4] Resolve mentions to IDs                  code (LLM only to canonicalize propositions)
  |          \
  |           +--> ambiguous? [5] Clarification question, then back to [4]
  v
[6] Build and validate PolicySpec            code, schema and semantic checks
  |
  v
[7] Impact and conflict check                SQL counts, existing policies
  |
  v
[8] Preview rendered from the spec           templates
  |
  v
[9] User confirms -> persist revision with source prompt -> async build
```

| Stage | Done by | Output |
|---|---|---|
| 1 Segment | LLM proposes spans, code verifies | List of constraint segments |
| 2 Route | Rules, LLM tiebreak | `access` or `confidentiality` per constraint |
| 3 Extract | LLM (constrained) | `ConstraintDraft` |
| 4 Resolve | Code, LLM for canonicalization | `ResolvedConstraint` |
| 5 Clarify | Code | `ClarificationRequest` |
| 6 Build | Code | `PolicySpec` (unpersisted) |
| 7 Impact, conflicts | Code | `ImpactReport`, conflict list |
| 8 Preview | Code (templates) | Preview text |
| 9 Confirm | Code | Persisted revisions |

---

## 4. Data contracts

### 4.1 ConstraintDraft (LLM output, stage 3)

Produced with grammar-constrained decoding against a JSON schema, so it always parses.

```json
{
  "effect": "deny",
  "principal_mentions": ["Agent A"],
  "modality": "knowledge",
  "object": { "type": "proposition", "text": "I have cancer" },
  "unsupported_parts": []
}
```

| Field | Values |
|---|---|
| `effect` | `deny`, `permit` |
| `principal_mentions` | One or more agent mentions. Code fans out to one constraint per agent. |
| `modality` | `access` (see, read, receive) or `knowledge` (know, learn, find out, be told) |
| `object.type` | `email_selector`, `proposition`, `topic`, `content_class` |
| `unsupported_parts` | Parts of the prompt the model could not map, each with a reason code |

Object variants:

```json
{ "type": "email_selector",
  "participants": [{ "mention": "John Smith", "role_mention": "from" }],
  "date_range": { "mention": "last year" },
  "account_mention": null }

{ "type": "proposition", "text": "I have cancer" }
{ "type": "topic", "text": "my financial information" }
{ "type": "content_class", "text": "flight and hotel reservations" }
```

`role_mention` is one of `from`, `to`, `cc`, `bcc`, `any`.

The LLM never outputs IDs, SQL, action lists, defaults or preview text.

**Substring guard.** Every `mention` and `text` value must appear in the prompt segment (case-insensitive, whitespace-normalized). A draft that fails the guard is rejected and retried once with the error. A second failure marks the constraint `unsupported` with reason `extraction_failed`. This prevents the model from inventing names or claims.

### 4.2 ResolvedConstraint (stage 4)

```json
{
  "effect": "deny",
  "kind": "confidentiality",
  "principal": { "agent_id": "agent_a", "matched_by": "alias" },
  "object": {
    "type": "proposition",
    "statement": {
      "canonical": "The user has cancer",
      "subject_entity_id": "person_self",
      "reuse_statement_id": null
    }
  },
  "assumptions": []
}
```

`matched_by` records how each ID was found (`exact_name`, `alias`, `address`, `user_choice`). It is shown in the preview.

### 4.3 ClarificationRequest (stage 5)

```json
{
  "draft_id": "dr_91",
  "constraint_index": 0,
  "question_code": "choose_person",
  "text": "Which John Smith?",
  "options": [
    { "id": "person_123", "label": "John Smith", "detail": "john.smith@acme.com · 312 emails" },
    { "id": "person_456", "label": "John Smith", "detail": "jsmith@gmail.com · 14 emails" },
    { "id": "none", "label": "Neither" }
  ],
  "round": 1,
  "max_rounds": 2
}
```

Option labels and details are generated by code from directory data, never by the LLM.

### 4.4 ImpactReport (stage 7)

```json
{ "matching_emails": 312, "matching_addresses": 2 }
```

For semantic rules: `{ "matching_emails": null, "note": "available after the build" }`. Nothing has been classified at interpretation time, so there is no honest count.

### 4.5 PolicySpec

The target object, defined in sections 3.1 and 3.2 of the main document. Its JSON Schema and Pydantic models are implemented in this step.

---

## 5. Stage details

### 5.1 Segmentation

A compound prompt ("Agent A can't see John's emails and can't know I have cancer") is split into one candidate constraint per clause.

- The LLM returns clause spans. Code verifies each span is a substring of the prompt, that spans do not overlap, and that nothing meaningful is left uncovered.
- Multiple agents ("Agents A and B") are fanned out by code into one constraint per agent.
- Each constraint goes through the rest of the pipeline and is previewed and confirmed on its own. The user can confirm some and not others.

### 5.2 Routing

The routing is decided by the **object**, not the verb.

| Object | Modality and effect | Result |
|---|---|---|
| Exact selector (person, sender, recipient, account, date range) | can't see, access, read, receive | Access, deny |
| Exact selector | can see, can access | Access, permit |
| Proposition ("I have cancer") | can't know, learn, find out | Confidentiality, deny, `kind: fact` |
| Topic ("my financial information") | can't see or know | Confidentiality, deny, `kind: topic` |
| Content class ("flight reservations") with permit | can see | Deferred, reported as unsupported in this step |
| Proposition or topic with permit | can know | Unsupported |
| Exact selector with `knowledge` modality | "can't know about emails from John" | Ask the user what they mean |

Notes:

- "Can't *see* that I have cancer" is still confidentiality, because the object is a proposition.
- "Agent A can only see emails from John" creates a permit. Default deny covers everything else. The preview lists Agent A's other existing grants, which stay in place, and points to the dashboard to remove them.
- "See emails about X" with a topic object becomes a span-level topic rule. The preview says: "Only the relevant sentences are hidden, not whole emails." Whole-email hiding by topic is not part of the model (open decision 1).

### 5.3 Extraction

- **Model:** a local instruct model run through Ollama or llama.cpp, temperature 0, grammar-constrained output. A small instruct-class model is likely sufficient because the task is extraction under a strict schema. This is to be confirmed on the golden set (open decision 3).
- **Prompt skeleton:** the system prompt defines the schema and the rules (extract mentions only, copy text verbatim from the prompt, never invent IDs, use `unsupported_parts` for anything else). It includes a few worked examples. The user's prompt is passed as quoted data, never as instructions.
- **Fast path:** a rule-based parser for the most common phrasings may be added later as an optimization. It must produce the identical `ConstraintDraft`.

Examples:

```json
// "Agent A can't know I have cancer"
{ "effect": "deny", "principal_mentions": ["Agent A"], "modality": "knowledge",
  "object": { "type": "proposition", "text": "I have cancer" }, "unsupported_parts": [] }

// "Agent A can't see emails from John Smith"
{ "effect": "deny", "principal_mentions": ["Agent A"], "modality": "access",
  "object": { "type": "email_selector",
              "participants": [{ "mention": "John Smith", "role_mention": "from" }],
              "date_range": null, "account_mention": null },
  "unsupported_parts": [] }
```

### 5.4 Resolution (deterministic)

**Agent**

- Exact or alias match against the agent registry, case-insensitive.
- No match: ask which registered agent. The interpreter never creates agents.

**Person**

- Candidates come from `EntityDirectory.search` (name, alias, address).
- "I", "me", "my" resolve to `person_self`.
- A **unique exact** match auto-resolves and is shown in the preview with how it was matched.
- Anything else (several matches, or only a fuzzy match) triggers a clarification. Fuzzy matches never auto-resolve.
- Relational mentions ("my wife", "my doctor") resolve only if the directory records the relationship. Otherwise ask.
- The LLM never sees the directory. It is not put in the model's context.

**Account** ("my work email"): exact match against registered accounts, otherwise ask.

**Date range:** relative expressions ("last year", "since March") are resolved against today's date in the owner's timezone and **frozen** to absolute dates at confirmation. The preview shows the absolute dates. Rolling windows are not supported in this step (open decision 8).

**Proposition (fact)**

1. **Canonicalize.** The local LLM, under constrained decoding, rewrites the proposition as one third-person statement, for example "The user has cancer", and returns flags: `atomic`, `is_question_or_instruction`.
2. **Check.**
   - Not atomic: split into several statements, each becoming its own constraint shown to the user.
   - A question or an instruction: rejected as unsupported.
   - A negated or hedged statement ("I don't smoke", "I might have cancer") is kept as written.
3. **Deduplicate in memory.** Compare the embedding with existing statements for the same subject. Reuse an existing `statement_id` only if two-way entailment holds (statement A implies B and B implies A, judged by the local model with a constrained yes/no output). Similarity alone never causes reuse. Otherwise create a draft statement.
4. Nothing is stored at this point. The embedding stays in memory.

**Topic:** same flow, canonicalized to a short noun phrase, deduplicated the same way.

### 5.5 Clarification

- Structured questions with selectable options, generated from code.
- A maximum of two rounds per constraint (open decision 2). After that the constraint stays `needs_review` and nothing is saved. The user can retry with a more specific prompt or use the dashboard editor.
- Each answer returns the draft to stage 4 for the affected mention only.

Question codes in this step: `choose_agent`, `choose_person`, `choose_account`, `choose_meaning` (for exact selector plus knowledge modality), `specify_information` (for prompts too vague to extract).

### 5.6 Build and validate

Code fills defaults from the PolicySpec schema:

| Field | Access policy | Confidentiality policy |
|---|---|---|
| `actions` | `email.search`, `email.read_content`, `email.read_attachment`, `email.read_extraction` | same |
| `treatment` | not used | `redact_span`, fallback `drop_segment` |
| `match_levels` | not used | `asserts`, `implies`, `evidence` |
| `enforcement.hold_until_ready` | not used | `false` |
| initial `status` | `active` | `building` |

Validation (Pydantic plus semantic checks). Any failure rejects the draft:

- Schema validity, no unknown fields.
- The principal exists and is active.
- Every entity and account ID exists.
- Selector is not empty, roles are valid, date range has start before end.
- Statement is atomic and non-empty.
- Actions are allowed for the policy type.
- The effect and type combination is supported (in this step: access permit and deny, confidentiality deny).

### 5.7 Impact and conflicts

**Impact.** For exact rules, the count service returns a number of matching emails and addresses (integers only, from metadata). Semantic rules get no count (section 4.4).

**Conflicts.** The new spec is compared with existing active policies for the same principal.

| Relation | Behaviour |
|---|---|
| Duplicate (identical normalized spec) | No new revision is created. The user is told which policy already covers it. |
| Narrower than an existing deny | Shown to the user as already covered. They may still confirm. |
| Broader than an existing deny | Shown. The old policy is not changed. |
| Permit and deny overlap | Shown with "deny overrides permit". |
| Same statement already protected for another agent | Informational. Existing findings will be reused. |

### 5.8 Preview

Rendered by templates from the final spec plus counts. Slots are filled from the spec, the registry and the count service. The LLM writes nothing the user reads.

**Access, deny, participant:**
> Agent A will not see the 312 emails sent by John Smith (john.smith@acme.com). Emails where he is only cc'd are not affected. Takes effect immediately.

**Confidentiality, deny, fact:**
> Agent A will not receive anything that states or strongly implies the following: "The user has cancer".
> Your wording: "Agent A can't know I have cancer".
> Affected parts are replaced by [REDACTED BY PRIVACY POLICY]. The rest of each email stays visible. Detection is AI-based and best-effort. Existing emails are processed first, and until that finishes the rule is not enforced.

**Confidentiality, deny, topic:** same, with "information about: "{topic}"" and the note "Only the relevant sentences are hidden, not whole emails."

Every preview also includes:

- **Assumptions** (role handling, "only" semantics, frozen dates, remaining grants).
- **Resolution notes** ("John Smith matched by exact name").
- **Enforcement status.** While enforcement is not live in the environment (a configuration flag), the preview adds: "Enforcement is not active yet. This rule is recorded only."

### 5.9 Confirm and persist

On confirm for one or more constraints, in one transaction per constraint:

1. Insert `authz.policy` (if new) and an immutable `authz.policy_revision` containing the spec and the encrypted `source` block (prompt, confirmed description, interpreter version, timestamp).
2. For a new statement: insert `semantic.protected_statement` (encrypted canonical text, subject, the in-memory embedding).
3. For semantic rules: insert `authz.policy_build` with status `building`.
4. Write an audit entry `policy_created` (policy id, revision, type, principal, interpreter version). No prompt and no statement text.
5. Enqueue the downstream jobs: term expansion, then candidate backfill and verification. In this step the jobs are enqueued but have no consumer yet.
6. Delete the draft.

Confirmation is idempotent on `(draft_id, constraint_index)`.

---

## 6. Draft state machine

Per constraint:

```text
extracted -> resolving -> needs_clarification -> resolving
                       -> ready (validated, previewed)
          -> unsupported (with reason codes)
          -> invalid (validation failed)
ready -> confirmed | abandoned | expired
```

- Drafts live in memory (or an encrypted ephemeral store) with a short TTL.
- Only `confirmed` writes anything to the database.
- `unsupported` and `invalid` give the user a reason and the supported part of the prompt, if any.

---

## 7. Walk-throughs

### 7.1 "Agent A can't know I have cancer"

| Stage | Result |
|---|---|
| 1 | One constraint. |
| 2 | Proposition object: confidentiality, deny, `kind: fact`. |
| 3 | `principal_mentions: ["Agent A"]`, `object.text: "I have cancer"`. |
| 4 | Agent A resolves to `agent_a` by alias. The statement is canonicalized to "The user has cancer" (subject `person_self`), atomic, no equivalent existing statement, so a draft statement is created in memory. |
| 6 | PolicySpec as in section 3.2 of the main document, status `building`. |
| 7 | No count. No conflicts. |
| 8 | The confidentiality preview from section 5.8. |
| 9 | Revision with `source`, statement `st_17`, build record, expansion job enqueued. |

### 7.2 "Agent A can't see emails from John Smith"

| Stage | Result |
|---|---|
| 1 | One constraint. |
| 2 | Participant selector: access, deny. |
| 3 | `participants: [{ mention: "John Smith", role_mention: "from" }]`. |
| 4 | Agent A resolves. John Smith has two candidates. |
| 5 | "Which John Smith? (a) john.smith@acme.com, 312 emails (b) jsmith@gmail.com, 14 emails". The user picks (a), so `person_123`. |
| 6 | PolicySpec as in section 4.4 of the main document, status `active`. |
| 7 | 312 emails, 2 addresses. No conflicts. |
| 8 | The access preview from section 5.8. |
| 9 | Revision with `source`. No statement, no build. |

---

## 8. Edge cases

| Case | Handling |
|---|---|
| Unknown agent | Ask which registered agent. Never create one. |
| Ambiguous person | Clarification list. No spec until chosen. |
| Vague ("keep my private stuff private") | `specify_information`: ask for the specific information. |
| Compound proposition ("I have cancer and I'm leaving my job") | Split into two statements, shown as two constraints. |
| Question or instruction as the object | Rejected as unsupported. |
| Double negation, "unless" clauses, time conditions | Unsupported in this step. The user is told and offered the supported part. |
| Contradiction with an existing policy | Shown with "deny overrides permit". |
| Hostile text in a directory name or the prompt | Contained by the schema, the substring guard, code-side validation and confirmation. |
| Third-party subject ("my wife is pregnant") | Resolved through the directory relation, or ask. |
| Content-class permit ("my travel agent can see flight reservations") | Reported as not yet supported. |
| Non-English prompt | Extraction is attempted. Preview language is an open decision (open decision 5). |

---

## 9. Staying local

- **Model:** local only, temperature 0, constrained output, fixed seed. The same prompt yields the same draft. `interpreter_version` is a hash of the model id, prompt template version, schema version and resolver versions, and is recorded on every revision.
- **Process isolation:** the interpreter runs in a process or container with no network egress. Embeddings and the entailment check also use local models.
- **No tools or write access for the LLM.** It cannot query or modify the database. Code does that, after validation.
- **Database access:** code reads the agent registry and entity directory, and calls the count service. It has no access to email content.
- **Prompt handling:** drafts are held in memory with a short TTL. The prompt is never logged. It is written once, encrypted, after confirmation (section 3.5 of the main document).
- **Logging:** only `draft_id`, stage timings, outcome codes and `interpreter_version`.
- **Owner-only entry point:** the interpreter is reachable from the dashboard session only. It is not exposed through MCP, so an agent can never create, edit or widen its own policy.
- **Injection:** the owner's own prompt is trusted, but entity names and pasted text can carry instructions. Containment comes from constrained decoding, the substring guard, deterministic resolution and validation, and human confirmation of a template-rendered preview.

---

## 10. Interfaces

Internal API, dashboard session only:

```text
POST   /v1/policy-drafts                    { prompt }                          -> DraftState
POST   /v1/policy-drafts/{id}/answers       { constraint_index, option_id }     -> DraftState
POST   /v1/policy-drafts/{id}/confirm       { constraint_indexes? }             -> { policies: [{ policy_id, revision, status }] }
DELETE /v1/policy-drafts/{id}
```

```json
DraftState {
  "draft_id": "dr_91",
  "expires_at": "...",
  "constraints": [
    { "index": 0,
      "state": "needs_clarification | ready | unsupported | invalid",
      "clarification": { ... },
      "preview": "...",
      "impact": { ... },
      "conflicts": [ ... ],
      "unsupported_parts": [ ... ] }
  ]
}
```

---

## 11. Component layout

```text
rosalind/policy/spec/                 PolicySpec v2 Pydantic models and JSON Schema
rosalind/policy/interpreter/
  service.py          orchestration and draft state machine
  segmenter.py
  router.py
  extractor.py        LLM wrapper: constrained decoding, retry, substring guard
  schemas.py          ConstraintDraft, ResolvedConstraint, ClarificationRequest, Preview
  resolvers/
    agents.py  people.py  accounts.py  dates.py  statements.py
  canonicalizer.py    proposition to canonical statement, atomicity check
  builder.py          PolicySpec construction and validation
  impact.py           count service client
  conflicts.py
  preview.py          templates
  drafts.py           ephemeral encrypted draft store
  persist.py          confirmation transaction
  versioning.py       interpreter_version hash
```

---

## 12. Storage created in this step

| Table | Content |
|---|---|
| `authz.policy` | Identity, owner, principal, status. |
| `authz.policy_revision` | Immutable PolicySpec plus the encrypted `source` block. |
| `authz.policy_build` | Created for semantic rules, status `building`. |
| `semantic.protected_statement` | Canonical statement, subject, embedding. Encrypted and access-restricted. Expansion terms are added after confirmation. |
| `audit.policy_event` | `policy_created` entries. No prompt, no statement text. |

Drafts are not stored in these tables.

---

## 13. Testing and evaluation

### 13.1 Golden set

A set of prompts mapped to expected outcomes, including multi-turn clarification. Start with a few hundred cases covering: varied phrasings, typos, several languages, compound and ambiguous prompts, unsupported constructs, injection attempts.

```json
{
  "id": "gs_0042",
  "prompt": "Agent A can't see emails from John Smith",
  "fixtures": {
    "agents": ["agent_a"],
    "people": [
      { "id": "person_123", "name": "John Smith" },
      { "id": "person_456", "name": "John Smith" }
    ]
  },
  "dialogue": [{ "expect_clarification": "choose_person", "answer": "person_123" }],
  "expected_specs": [{ "type": "access", "effect": "deny", "principal": "agent_a",
                       "selector": { "entity_id": "person_123", "roles": ["from"] } }]
}
```

### 13.2 Metrics and gates

| Metric | Target |
|---|---|
| Wrong agent or wrong entity in a confirmed spec | **Zero**. Hard release gate. |
| Wrong statement reuse (two statements judged equivalent but not) | Near zero. Hard release gate. |
| Field-level spec accuracy on supported prompts | Tracked, regression gate. |
| Unsupported detection (precision and recall) | Tracked. |
| Clarification precision | Asks when truly ambiguous, never when there is a unique exact match. |
| Determinism | Same prompt gives the same draft across repeated runs. |
| Preview coverage | Every spec field is rendered or listed as a default. Tested by perturbing each field. |
| Injection suite | Hostile directory names and prompts never alter spec fields beyond the schema, never add constraints, never change the preview. |
| Latency | Interactive on the owner's hardware. The target is measured in the first iteration. |

A new interpreter version cannot ship if the golden set regresses.

---

## 14. Acceptance criteria for this step

- The two example prompts work end to end, including the John Smith clarification.
- Confirmed policies are persisted with the encrypted `source` block, and nothing is persisted before confirmation.
- Semantic rules create a statement and a build record. Exact rules are `active` immediately.
- The preview is generated from the spec and states clearly that enforcement is not active yet.
- All interpretation runs locally with no network egress, and the prompt appears in no log.
- The golden set passes its hard gates.
- The interpreter is not reachable from MCP.

---

## 15. Open decisions

1. **Whole-email topic requests:** "see emails about X" currently becomes span-level redaction with a preview note. Alternative: ask whether the user also wants whole emails hidden (this would need a model change).
2. **Clarification rounds:** a maximum of two, then `needs_review`. Alternative: allow unlimited rounds.
3. **Model choice:** which local model and size, validated on the golden set.
4. **Draft store:** in-process memory, or an encrypted ephemeral store if the service runs several workers.
5. **Preview languages:** English only first, or the language of the prompt from the start.
6. **Natural-language edits and revocations** ("remove my rule about cancer"): dashboard only in this step.
7. **"Only" semantics:** a permit that leaves other grants in place (current default), or an option to replace them.
8. **Rolling date windows** ("the last 12 months" that moves with time): unsupported now, since dates are frozen at confirmation.
9. **Content-class permits** (allow-lists by content): deferred to the semantic pipeline.
