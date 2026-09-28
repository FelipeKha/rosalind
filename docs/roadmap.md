# Rosalind — Roadmap

**Phase:** 2 — Personal Knowledge Graph

---

## 0. Where we are

Phase 1 (MVP) is complete: import tracking, raw source persistence, the Google
Contacts pipeline, the canonical person model, `agent.person_profile`, and a
read-only MCP server backed by `search_people` / `get_person`. See
`DESIGN.md` for the architecture those pieces implement.

## 1. What changes in Phase 2

Phase 1 was about proving the pipeline: provider payload → raw evidence →
canonical person. Phase 2 is not "import two more providers." The MVP already
told us how to ingest; it did not tell us how to *connect* or *retrieve*.

**The objective going forward: progressively build a connected personal
knowledge graph that an agent can retrieve from — not simply import more
data.**

Every milestone below should be judged against one question:

> Does this let an agent reliably answer a class of question it could not
> answer before?

```text
Contacts
→ "Who is Greg?"

Contacts + Gmail (linked)
→ "What have I discussed with Greg?"

Gmail + structured/lexical search
→ "Find the emails about the market report."

People + Gmail + temporal retrieval + self_person_id
→ "Who sent me the last market report?"

People + Gmail + semantic retrieval
→ "Where did Greg suggest we meet next week?"

People + Gmail + Calendar
→ "When did I last meet Greg, and what did we discuss beforehand?"
```

The three things we said we wanted — Contacts + Gmail linked, search, and a
smarter MCP — map onto this progression, but identity resolution and "who is
me" turn out to be the load-bearing pieces underneath all three, so they're
pulled out as their own milestone rather than being buried inside Contacts or
Gmail.

---

## 2. Phase 2.1 — Identity: Contacts + "who is me"

Contacts import itself is mostly done. What's missing is making
`core.source_identity` actually do its job across providers, and telling
Rosalind who its own user is.

### 2.1.1 `self_person_id`

DESIGN.md §11 and §23.3 deliberately deferred `account.self_person_id` and
`get_my_profile` in the MVP — correctly, since there was no second data
source yet to make "me" meaningful. Phase 2 needs it: **"who sent me the
last market report" and "where did Greg suggest we meet" both require
Rosalind to know which `core.person` is the account owner.** Without it, two
of the three motivating queries for this phase don't actually resolve.

Scope for this milestone:

* `account.self_person_id → core.person`, nullable, set explicitly (not
  inferred).
* A minimal way to set it (CLI command or one-off API call is enough — no UI
  needed yet).
* `get_my_profile` MCP tool, now unblocked, read-only, same pattern as
  `get_person`.

### 2.1.2 Deterministic identity resolution — with a concrete mechanism

The plan is "deterministic matching, not fuzzy/LLM resolution yet." That's
right, but the roadmap needs to pin down the mechanism, not just the policy,
so it isn't improvised mid-implementation:

* Matching key for Phase 2: normalized email address
  (`core.person_email.email_normalized`), plus exact provider identity where
  one already exists (existing `core.source_identity` behavior).
* **On match:** create a new `core.source_identity` (e.g.
  `source_type = 'GMAIL_PARTICIPANT'`) pointing at the existing person, and
  link the new assertion to the existing canonical facts as usual.
* **On no match:** do *not* auto-create a new `core.person` for every unknown
  email participant. An inbox will contain hundreds of one-off senders
  (mailing lists, receipts, strangers), and auto-minting a person per address
  would flood `core.person` with noise. Instead:
  * Gmail participants without a resolved person are stored as unresolved
    (email address only) — this is already allowed by the participant model
    in DESIGN.md §28/§29.
  * A person is only created from an email address when it's promoted
    explicitly — either by a later, deliberate reconciliation pass, or by the
    user/agent taking an action that implies "this is a person I care about"
    (e.g. explicitly linking them). This is a policy decision worth revisiting
    once we see real data, but "don't auto-mint" is the safe default to ship
    with.
* Phone number normalization is a plausible second matching key later; not
  in scope now.

### 2.1.3 Acceptance

* Given a Contacts person and a Gmail participant with the same email, they
  resolve to one `core.person`.
* An unmatched Gmail sender does not create a new person.
* `self_person_id` can be set and read via `get_my_profile`.
* Re-running resolution on already-linked data is idempotent (no duplicate
  `source_identity` rows).

---

## 3. Phase 2.2 — Gmail: messages, threads, participants, attachments

Gmail is a genuinely different domain from Contacts: it's events and
relationships, not attributes. Per DESIGN.md's own philosophy (§28), don't
force it into the `person_*` canonical fact tables. New tables, same
provenance discipline:

```text
core.email_thread
core.email_message
core.email_participant
core.email_attachment
```

Raw persistence, source assertions, and provenance follow the same pattern
already established for Contacts (raw first, parse/validate second, never
discard the payload on a mapping failure).

### 3.1 Messages and threads

Preserve, at minimum: subject, body (text/html), sent/received timestamps,
thread linkage, in-reply-to. Don't reduce a message to a text blob — the
metadata (who, when, to whom) is what makes structured queries like "who
sent me X" answerable without touching search at all.

### 3.2 Participants

From/to/cc/bcc, each initially an email address, resolved to a
`core.person` using the mechanism from 2.1.2 where possible. A message is
never discarded or blocked on an unresolved participant.

### 3.3 Attachments — reuse the existing storage pattern, don't invent a new one

DESIGN.md §7.3 already has an object-storage pattern for import files
(CLI uploads bytes, backend owns metadata and storage keys, originals kept
independently of canonical entities). Attachments should reuse that path
rather than solving "where do bytes live" a second time.

Scope for Phase 2:

* Attachment **metadata** as a first-class part of the Gmail milestone, not
  an implementation detail: filename, MIME type, size, provider attachment
  ID, object-storage reference, linked to `core.email_message`.
* The raw attachment bytes are preserved (same immutability guarantee as
  `raw.source_record`), regardless of type — PDF, spreadsheet, image, zip
  all just get stored.
* **Explicitly deferred:** content extraction (PDF text, OCR, spreadsheet
  parsing) and any attachment-content search. That's a separate milestone,
  later, once there's a reason to search inside attachments rather than just
  know they exist. Shipping extraction now risks turning this phase into a
  document-processing project instead of a knowledge-graph one.

### 3.4 Acceptance

* A Takeout Gmail export imports as raw evidence first, every message/thread
  survives a parser error on some other message (quarantine per-record, not
  per-import).
* Re-importing the same export is idempotent (no duplicate messages).
* Attachment metadata is queryable; attachment bytes are retrievable; no
  extraction yet.
* At least one participant per test fixture resolves to an existing
  `core.person` from Contacts.

---

## 4. Phase 2.3 — Retrieval: structured and lexical

Search is a capability across domains, not a feature bolted onto Contacts or
onto Gmail separately. DESIGN.md §24/§39 already specifies this layering;
this phase implements the first two layers.

### 4.1 Structured

Postgres relational queries, no new infrastructure:

* "Who is Greg?" → person lookup (already have this).
* "Show emails from Greg." → participant join, ordered by `sent_at`.
* "Who sent me the last market report?" → requires `self_person_id`
  (recipient = me) + a lexical filter on subject/body, ordered by `sent_at`,
  limit 1. This is the concrete reason 2.1.1 has to land before this phase
  is useful.

### 4.2 Lexical

Postgres full-text search / trigram, per DESIGN.md §24, on message
subject/body. Enough to answer "find emails mentioning X" without embeddings.

### 4.3 Explicitly out of scope here

Semantic search. "Where did Greg suggest we meet next week?" likely needs
it, because the answer may be phrased as "How about Le Dauphin on Wednesday?"
with no lexical overlap to "meet" or "next week." That's Phase 2.5, not this
one — noted here so it's a known limitation of this phase rather than a
surprise.

### 4.4 Acceptance

* Structured queries above return correct, ordered results against
  fixture data.
* FTS/trigram search returns reasonable matches for paraphrased-but-close
  queries ("market report" matches "Q3 market update").
* No vector/embedding infrastructure introduced yet.

---

## 5. Phase 2.4 — Agent interface: composable retrieval, not answer-shaped tools

MCP stays thin (DESIGN.md §23, invariant #22–24) and grows by adding
**reusable retrieval primitives**, not one tool per example question:

```text
find_people(...)          (exists, extend if needed)
get_person(...)           (exists)
get_my_profile(...)       (new, from 2.1.1)
search_messages(...)      (new)
get_message(...)          (new)
search_threads(...)       (new)
```

Not this:

```text
find_where_greg_suggested_meeting()   ✗
find_last_market_report()              ✗
```

The agent composes primitives across turns. "Who sent me the last market
report?" becomes: `search_messages(recipient=me, text≈"market report",
order=recent, limit=1)` → resolve sender via the message's participant link.
"Where did Greg suggest we meet?" becomes multi-step once semantic search
exists in 2.5: resolve Greg → `search_messages(participant=Greg,
semantic="suggest a place/time")` → `get_message` for the thread context →
answer with provenance.

Every MCP response should be able to cite back to source assertions /
messages (DESIGN.md §23.11 already anticipates this; Phase 2 is a reasonable
point to start actually surfacing it, even minimally, since "answer with
provenance" is part of what makes these answers trustworthy).

Still read-only in this phase — no write tools, consistent with invariant
#25 and the existing deferral of the write/auth model.

### 5.1 Acceptance

* New MCP tools follow the same schema/session/logging discipline as
  `search_people`/`get_person` (§23.6–§23.13).
* An agent can answer "who sent me the last market report" using only
  structured/lexical primitives from 2.3, composed across two tool calls.
* Tool descriptions are accurate about read-only status and result bounds,
  per existing convention.

---

## 6. Phase 2.5 — Semantic retrieval

Only after 2.3/2.4 exist and are useful on their own. `pgvector`, embeddings
on message bodies (natural-language content only — not structured facts,
per DESIGN.md §24's existing philosophy, which this plan keeps unchanged).
Hybrid retrieval (structured filter + semantic rank) is what actually
answers "where did Greg suggest we meet."

Not detailed further here — revisit once 2.1–2.4 are shipped and we know
what real queries actually need.

---

## 7. Phase 2.6 — Calendar

After Gmail, not before — once people + communications exist, Calendar adds
a third relational domain and the questions genuinely start crossing
domains:

```text
Person ↕ Email ↕ Calendar event ↕ Person
```

> "When was the last time I met Greg?"
> "What did we discuss before that meeting?"
> "Did Greg send me anything afterwards?"

Same ingestion discipline as Contacts/Gmail (raw-first, provider adapter,
observations, canonicalization). Not detailed further here.

---

## 8. Sequencing notes

* **2.1 and 2.2 will interleave in practice.** Identity-resolution logic
  can't be fully validated without real Gmail participant data to resolve
  against, and Gmail participant linking depends on 2.1's mechanism
  existing. Treat this as one working set, not a strict waterfall — but keep
  `self_person_id` and the match/no-match policy decided *before* writing
  Gmail participant-linking code, so that code has something concrete to
  call.
* Attachment **content extraction**, semantic search, and Calendar are all
  explicitly future phases (2.5, 2.6, and beyond) — not silently assumed to
  be "done" by anything in 2.1–2.4.
* Each phase's acceptance criteria double as its stated limitations: if a
  query isn't listed as answerable in a phase's acceptance section, it isn't
  expected to work yet.

---

## 9. Summary table

| Phase | Adds | Unlocks |
|---|---|---|
| 2.1 | `self_person_id`, deterministic identity resolution | "Who is Greg?" cross-provider; "me" is known |
| 2.2 | Gmail messages/threads/participants/attachment metadata | "What have I discussed with Greg?" |
| 2.3 | Structured + lexical search | "Find emails about the market report"; "Who sent me the last market report?" |
| 2.4 | Composable MCP retrieval primitives | Agent can chain primitives to answer multi-step questions, with provenance |
| 2.5 | Embeddings, pgvector, hybrid retrieval | "Where did Greg suggest we meet next week?" |
| 2.6 | Calendar | "When did I last meet Greg, and what did we discuss beforehand?" |
