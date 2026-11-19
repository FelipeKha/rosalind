# Rosalind — Confidentiality (Semantic) Enforcement (Implementation Step 3)

Companion to `rosalind_policy_engine_rag_filtering_v7.md`, `rosalind_policy_interpreter.md` and `rosalind_access_enforcement.md`. This document plans how **confidentiality policies** (protected statements and topics) are enforced in the RAG, down to the span. It is the third implementation step.

---

## 1. Purpose and scope

**What a confidentiality constraint is.** It protects a piece of information (a statement such as "The user has cancer", or a topic) wherever it appears in text, down to the span. It cannot be decided from stored attributes. It is decided by interpreting content, so it is model-based and best-effort, unlike an access constraint, which is an exact SQL condition (step 2).

**Goal, using our example.** With the rule "Agent A can't know I have cancer" active, Agent A asks "when is the meeting?" and gets `[REDACTED BY PRIVACY POLICY], let's meet tomorrow at 10am.` with the source email ID. Asking for the full email returns the same sanitized text. Searching "chemotherapy" finds nothing from the doctor's email.

**Builds on the previous steps**

- Step 1 persisted policies, protected statements and build records, and enqueued jobs with no consumer. Step 3 provides the consumers.
- Step 2 provides the `ScopedReader`, `EffectiveScope`, L2 verification and the audit pipeline. Step 3 plugs into the extension points defined there.

**Structure.** Because the outcome is a measured recall number, not a pass or fail, this step is organized as five **slices**, each with a gate (section 9). In the roadmap of the main document (v7) this step covers Phases 3, 4 and 5. Merging them into one step is open decision 1.

**In scope**

- Segment store, candidate generation, local verification, findings, provenance.
- Cut-plus-marker sanitization, and the overlay index used by retrieval.
- Asynchronous build, coverage, incremental processing, model-health handling.
- JIT verification, the final gate (as an experiment first), and `hold_until_ready`.
- All MCP tools, derived data (extractions, entity attributes), term-level features (snippets, autocomplete, facets).
- The evaluation harness and its gates.

**Out of scope**

- The full dashboard (Phase 6), probing protections and rate limiting (Phase 7).
- Content-based grants (allow-lists by content).
- Natural-language edits of policies.

---

## 2. Principles

1. **Measure before building.** Recall is the product. Each slice ends with measured numbers, not a feature checklist.
2. **Findings belong to segments, not agents.** An agent only selects which statements apply (the semantic set).
3. **Replace before ranking.** Protected text never takes part in an agent's search ranking. Redacting after ranking creates an oracle.
4. **Non-blocking by default, always transparent.** A rule that is not ready is not enforced, and the user is told. Holding is opt-in.
5. **Smallest safe unit.** Span first, then segment, then chunk. Never the whole email.
6. **Sanitized text is computed once** and stored. Search and `get_item` return byte-identical text.
7. **Everything runs locally** with one resident model. Interactive work has priority over background work.
8. **A deterministic floor under the model.** Model output can add findings but never remove a deterministic one, and email text is untrusted input to the model.
9. **Fail visible.** If the model is down or a build fails, the rule is shown as pending or failed, never silently active.

---

## 3. Assumptions to verify (slice 0)

| # | Assumption | Why it matters |
|---|---|---|
| S1 | Rosalind already chunks text and embeds chunks. Chunk size and boundaries are known and stable. | Overlay rows are sanitized copies of chunks. |
| S2 | The BM25 index can hold extra rows with a scope column and shared statistics. | Overlay and base rows must score comparably. |
| S3 | The embedding model and dimension, and its throughput on the development laptop. | Cost of segment embeddings and of re-embedding overlay chunks. |
| S4 | The job system supports priorities, checkpoints and throttling. | Backfill must yield to interactive work. |
| S5 | Extraction and entity provenance granularity: span offsets or email-level only. | Derived-data rules (section 7.7). |
| S6 | Attachment text extraction, OCR availability and quality. | Attachments are text sources. |
| S7 | Mailbox size, segments per email, language mix. | Drives the throughput budget (section 10). |
| S8 | Quoted and forwarded blocks are identifiable at parse time. | Quoted-copy handling (section 7.8). |
| S9 | The runtime exposes token log-probabilities, or we need another confidence source. | Thresholds (section 6.3). |
| S10 | The hardware available for backfill (laptop only, or a stronger local machine). | Backfill duration. |

---

## 4. Architecture

### 4.1 Offline pipeline (asynchronous)

```text
New or existing email
   |
   v
Segmentation  -> search.segment (offsets into field text, text_hash, chunk link)
   |
   v
Segment embeddings (stored, one-time per segment)
   |
   |   For each active statement (building or active):
   v
Candidate generation   lexical expansion + embedding similarity + recognizers   (recall-oriented, never blocks)
   |
   v
Verification (local model, constrained output)    window of neighbouring segments
   |
   v
Findings (verdict, spans, raw score, classifier_version) + coverage marks
   |
   v
Overlay builder  -> sanitized chunk copies (display_text, index_text, embedding, BM25 row)
   |
   v
Status and coverage  -> policy_build, dashboard, notifications
```

### 4.2 Online path (extends step 2)

```text
[1] Authenticate
[2] Load scope (snapshot): EffectiveScope now includes `semantic` (statement set, statuses)
[3] ScopedReader: access predicates (step 2)
    + overlay join: base rows replaced by the agent's overlay rows         <- new
[4] Verify returned items (step 2 L2)
    + JIT verification of returned chunks not yet processed                <- new
[5] Assemble: render display_text, redactions field, derived-data filters,
    term-level features from overlay                                       <- new
    + final gate (experiment first)                                        <- new
[6] Respond, audit (adds redaction events)
```

### 4.3 Terms

| Term | Meaning |
|---|---|
| Segment | A sentence or clause. The unit of verification and hashing. |
| Chunk | The existing retrieval unit. Several segments make a chunk. |
| Finding | "Segment S asserts, implies or evidences statement T", with the protected spans. |
| Candidate | A segment the funnel considers possibly relevant to a statement. |
| Semantic set | The set of statements, with treatments and thresholds, that applies to an agent. Hash: `set_id`. |
| Overlay row | A sanitized copy of a chunk for one semantic set. |
| Coverage | How much of the archive has been processed for a statement. |

---

## 5. Data model

Names are illustrative. Slice 0 maps them to the real schema.

| Table | Content |
|---|---|
| `search.segment` | `segment_id`, `email_id`, `field` (subject, body, attachment, quoted), `chunk_id`, `ordinal`, `start`, `end` (offsets into canonical field text), `text_hash`, `language`, `is_quoted`, `embedding`. |
| `semantic.protected_statement` | From step 1. |
| `semantic.statement_expansion` | Terms and concepts per statement, in several languages, generated after confirmation. |
| `semantic.candidate` | `segment_id`, `statement_id`, source (lexical, embedding, recognizer), score. |
| `semantic.coverage` | `segment_id`, `statement_id`, stage reached (candidate-checked, verified), `classifier_version`. This distinguishes **processed negative** from **unprocessed**. |
| `derived.finding` | `segment_id`, `statement_id`, verdict, subject match, spans (as offsets), `raw_score`, `classifier_version`. |
| `semantic.model_run` | Model ID, quantization, runtime version, prompt template version, schema version, window configuration. Its hash is `classifier_version`. |
| `semantic.set` | `set_id` and its members (statement, treatment, match levels, threshold profile). |
| `search.chunk_overlay` (or rows in the main index, section 6.6) | `set_id`, `chunk_id`, `display_text`, `index_text`, `redactions` (offsets), `embedding`, BM25 entry, copied access attributes, `findings_hash`, `status` (provisional or complete). |
| `search.field_overlay` | Same idea for subjects and attachment names. |
| `semantic.job` | Job type, priority, checkpoint, state. |
| `semantic.review_item` | Spot-check queue: low-confidence findings, borderline negatives, random samples. |
| `authz.policy_build` | From step 1, extended with counters: segments total, candidates, verified, flagged, pending, estimated time remaining, state. |

**Rules**

- `classifier_version` is a hash of the model ID, quantization, runtime version, prompt template version, schema version and window configuration. **Thresholds are not part of it**, so changing a threshold rebuilds overlays but does not re-run the model.
- **Storage security.** `derived.*`, `semantic.*` and the spans are sensitive metadata ("this email touches the protected statement"). The agent-facing DB role has no access to them. Statement text stays encrypted (step 1).
- Overlay rows carry copies of the access attributes of the base row, so step 2's predicates apply to them unchanged. The consistency job from step 2 covers them.

---

## 6. Offline pipeline

### 6.1 Segmentation

- A sentence and clause splitter for email text: body, subject, attachment text, quoted blocks (flagged `is_quoted`). Signatures and boilerplate are marked but not dropped.
- Every segment stores offsets into the canonical field text, and a link to its chunk, so a protected span can be mapped back to chunk coordinates for the cut.
- `text_hash` is computed on normalized text (case, whitespace and quote prefixes normalized).
- Segmentation does not need to be perfect. The verifier returns the exact protected substring inside the segment, so comma-spliced sentences like "I have cancer, let's meet tomorrow" are cut inside the segment.
- Segmentation is incremental: new and updated emails produce new segments, and unchanged segments keep their findings.

### 6.2 Candidate generation (the funnel)

A full model pass over every segment for every statement is not affordable (section 10). A cheap, recall-oriented funnel selects candidates. It never blocks anything by itself.

| Source | How |
|---|---|
| Lexical | Terms and concepts from `statement_expansion` (multilingual), matched with BM25 or regex over segments. |
| Embedding | Similarity between the statement embedding and **stored segment embeddings**, with a low threshold. |
| Recognizers | Presidio-style recognizers and taxonomy tagging (health, finance, identity) as extra candidate sources. |

- **Segment embeddings are stored.** Chunk-level similarity dilutes a single sensitive sentence inside a long chunk, so it would lose recall. The cost (storage and one-time compute) is measured in slice 0. Reduced dimension or half precision may be needed. Open decision 7.
- Candidate thresholds are set from the benchmark, per statement type (section 8). Real statements are never sent to a hosted model for calibration (section 8.1).
- **Candidate recall is measured on its own.** It caps the recall of the whole pipeline.
- Every segment checked by the funnel gets a `semantic.coverage` mark, whether or not it became a candidate.

### 6.3 Verification

A local model judges candidates against the statement, with context.

**Input.** The target segment, a context window of neighbouring segments in the same field (default ±2, tuned in slice 0), the subject line, and participant display names. The text is passed as quoted data, never as instructions. Several candidate segments in the same chunk are verified in one call, and several statements for the same window can share a call.

**Output** (constrained decoding):

```json
{ "results": [ {
    "statement_id": "st_17",
    "subject_matches": true,
    "verdict": "asserts | implies | evidence | none",
    "spans": ["I have cancer,"]
} ] }
```

- `subject_matches` forces the model to check whether the statement's subject is the person the segment is about. "My mother has cancer" is not "The user has cancer".
- **Spans are substrings, not offsets.** Models are poor at offsets. Code locates each returned substring in the segment, and the substring guard rejects anything that is not found. A rejected span falls back to treating the whole segment as protected.
- A verdict is a finding only if it is in the policy's `match_levels`.
- **Confidence.** Prefer verdict-token log-probabilities if the runtime exposes them (S9). Otherwise use agreement across two prompts or two models. Self-reported confidence is not used on its own.
- **Recall levers.**
  - Thresholds tuned for recall.
  - Borderline candidates get a second opinion from a different model or prompt, and the findings are unioned.
  - **Deterministic floor.** A very high-similarity candidate that the verifier dismisses gets a second opinion, and the recognizers' findings cannot be removed by the model.
- **Injection hardening.** Constrained schema, quoted data, substring guard, deterministic floor, and an injection test set (section 8.4).
- **Verifier model.** The model chosen for the interpreter is the starting point. The bake-off (Qwen 3.5 9B, Gemma 4 E4B, Ministral 3 8B) is repeated on this task in slice 0, since the interpreter's winner may not be the best verifier.

### 6.4 Findings, propagation and versioning

- **Positive findings propagate across identical content hashes.** If a sentence is flagged in one email, the same normalized sentence elsewhere (a quoted copy, a forwarded message) inherits the finding. **Negatives never propagate**, because the same sentence can mean something else in a different context. This favours recall.
- Findings are re-run when `classifier_version` changes, restricted to candidates, so it is bounded.
- A finding that the owner marks as wrong in the spot-check queue is stored as an override for that segment and statement, and is respected by later runs.

### 6.5 Sanitization (cut and mark)

Sanitization works per chunk, for a semantic set, and produces `display_text` and `index_text`.

1. Collect the flagged spans of all statements in the set, mapped to chunk coordinates. Snap boundaries to word boundaries.
2. Merge overlapping and adjacent spans. Each merged span becomes one marker `[REDACTED BY PRIVACY POLICY]`. The marker is identical for every rule, agent and length.
3. **Treatment.** `redact_span` cuts the spans. `drop_segment` replaces whole segments.
4. **Safety check.** The verifier runs on the sanitized chunk text, with the same window. If it still finds the statement, escalate.
5. **Escalation ladder:** span, then segment, then neighbouring segments in the window, then the whole chunk. Never the whole email.
6. **Boundary check.** A recognized date, time or entity that is partially covered by a span is reported, and the span boundary is adjusted when the date, time or entity is not itself protected. Utility retention is otherwise a metric, not a gate, because the remaining text is unchanged by a cut.
7. `index_text` is the same text **without** the marker, so searching "redacted" matches nothing.

Subjects and attachment names go through the same path (`field_overlay`) and are used wherever those fields are returned.

### 6.6 Overlay builder

- For each (semantic set, chunk) with findings, create an overlay row: sanitized text, a new embedding of `index_text`, and a BM25 entry.
- **Single index with a scope column** (proposed): base rows have no set, overlay rows carry `set_id`, so BM25 statistics stay comparable. Separate indexes would make scores incomparable. Slice 0 verifies this against the actual BM25 extension (S2).
- Base rows carry a list of the sets that replace them (`replaced_in_sets`, GIN-indexed), maintained by the builder. Retrieval then uses `NOT (replaced_in_sets @> :set)` instead of an anti-join. Slice 0 compares both.
- **No window where the original leaks after a finding exists.** When a positive finding is written, the same transaction marks the base row as replaced for the affected sets and writes a **provisional** overlay row (text and BM25 entry computed immediately, embedding pending). Until the embedding exists the row is reachable by BM25 only, never by vector search. The builder then completes it.
- Dirty-chunk queue with coalescing: many findings in one chunk cause one rebuild.
- Adding or removing a statement from a set recomputes only the affected chunks.
- Overlay rows whose set is referenced by no active policy are garbage-collected.
- Chunks with no findings in a set have no overlay row.

### 6.7 Scheduling, resources and model health

One resident model serves four consumers, in priority order:

| Priority | Consumer |
|---|---|
| P0 | JIT verification (interactive agent request) |
| P1 | Policy interpreter (interactive owner request) |
| P2 | Incremental processing of newly ingested emails |
| P3 | Backfill for new rules and classifier-version re-runs |

- Lower priorities yield between calls. Jobs are checkpointed, idempotent and resumable.
- Throttling when the owner is active. Thermal and memory pressure monitoring.
- **Model health:** if the model is unavailable, jobs pause. Affected policies show "paused: model unavailable". No rule becomes active by default, and the user is notified.
- Calls are grouped by chunk and share a cached static prompt prefix.

### 6.8 Status and coverage

- `authz.policy_build` is updated continuously: segments total, checked by the funnel, candidates, verified, flagged, pending, and an ETA computed from observed throughput.
- `building` becomes `active` when the existing archive has been processed. New items afterwards are handled incrementally, and the dashboard shows the pending count.
- Coverage means **processed**, not **correct**. The dashboard labels semantic rules as AI-detected, and reports the measured reliability for the statement type once the benchmark exists (open decision 14).

### 6.9 Lifecycle changes

| Event | Effect |
|---|---|
| Policy paused or revoked | The set is recomputed. Overlays no longer referenced are garbage-collected. Findings stay, because they belong to segments. |
| Policy edited (treatment, match levels) | New revision, new set, overlay rebuild from existing findings. |
| New statement for an agent | New set. Backfill runs only for statements without coverage. |
| Same statement, second agent | Same findings, new or shared set. No re-verification. |
| Classifier version change | Candidates re-verified in the background, overlays rebuilt, caches and cursors invalidated. |
| Statement deleted | Findings and coverage for it are removed when no policy references it. |

---

## 7. Online path

### 7.1 Scope extension

`EffectiveScope` replaces `pending_semantic` with `semantic`:

```json
"semantic": {
  "set_id": "ss_9d2f",
  "statements": [ {
    "policy_id": "pol_41", "statement_id": "st_17",
    "match_levels": ["asserts", "implies", "evidence"],
    "treatment": { "mode": "redact_span", "fallback": "drop_segment" },
    "status": "building", "hold_until_ready": false
  } ]
}
```

- Confidentiality policies in `building` or `active` status are included. In `building`, the overlay applies for whatever has been processed so far.
- `set_id` is part of `scope_fingerprint`. Overlay rows are keyed by `set_id`, not by the whole fingerprint, so agents with the same statements but different access scopes share overlays. (The main document currently keys overlays by scope fingerprint and will be aligned.)

### 7.2 Retrieval with overlay

```text
visible rows =  base rows in access scope
                   whose replaced_in_sets does not contain :set_id
             UNION overlay rows for :set_id in access scope
```

- BM25 and vector legs both use this. Fusion, reranking and pagination run over the union.
- Overlay rows carry the same access attributes, so the step 2 predicates apply to them without change.
- Step 2's vector strategy selector (exact scan or ANN with fallback) works over the union. Slice 0 checks that overlay rows do not break recall.

### 7.3 JIT verification

- **When.** After reranking, returned chunks that have no coverage mark for a statement in the agent's set (the rule is still `building`, or the email is new).
- **What.** The cheap funnel runs synchronously on those segments (stored embeddings and lexical checks). Only the flagged ones go to the verifier. For `get_item`, every chunk of the item is covered. For `search`, the top-k are.
- **Priority and budget.** P0, with a hard per-request time budget so MCP clients do not time out. Results are persisted, so later reads are identical.
- **On timeout.** Default: return as-is and record the segments as pending in the audit. With `hold_until_ready`: exclude the chunk from search results, and show the marker in item reads.

### 7.4 Assembly and rendering

- Return `display_text` (with marker) and the `redactions` field. The original text of an affected chunk is never loaded for the agent.
- Search and `get_item` read the same stored overlay row, so their text is byte-identical.
- Snippets and highlights are generated from `index_text` or `display_text`, never from base text.
- Step 2's L2 verification still applies. A new L2 check is added for semantic output: every returned chunk that has findings in the agent's set must be an overlay row.

### 7.5 Final gate (experiment first)

- A local check of the assembled context against the statements, for combinations that individual segments do not reveal (for example E3 "I hope you feel better" plus E4 "medical appointments").
- It costs another model call per request on the laptop. In slice 4 we measure what it catches that segment-level checks miss. If the gain is small, it becomes a **sampled offline audit** instead of an inline step.
- Action when inline: replace the least-certain segments with the marker and log the event.

### 7.6 Changes per tool (on top of step 2)

| Tool | Addition |
|---|---|
| `search` | Overlay union, JIT on top-k, snippets from overlay text. |
| `get_item` | Full JIT, overlay rendering, subject and attachment names from field overlays. |
| `get_thread` | Sanitized messages, thread subject from the field overlay, thread aggregates computed on sanitized content. |
| `get_context` | Neighbours through the same path. |
| Attachments | Names and extracted text sanitized the same way. Unverifiable content (no usable OCR) is open decision 11. |
| `list_extractions`, `find_entity` | Section 7.7. |
| Autocomplete, facets, suggestions, related terms | Computed from overlay text, so protected terms never appear as suggestions. |
| `describe_capabilities` | No information about rules or coverage. |

### 7.7 Derived data

- Extractions and entity attributes must follow the visibility of their evidence **at span level**. An extraction is hidden if its evidence spans overlap a flagged span in the agent's set.
- This needs span offsets in the provenance (S5). If Rosalind stores only email-level provenance, the fallback is conservative: hide the extraction when its email has any finding for the set. That over-hides, so adding span-level provenance is a work item in slice 3.
- A fact extracted from "I have cancer" is hidden. A fact extracted from "let's meet tomorrow at 10am" stays visible.

### 7.8 Quoted-copy masking for access denies (proposed)

This closes the step 2 limitation: Mary's reply quotes John's denied email. With the segment store, it is cheap.

- For an agent with a deny clause, compute the denied emails (SQL). Take their non-quoted segment hashes.
- In **visible** emails, segments flagged `is_quoted` whose hash matches are replaced by the marker through the same overlay mechanism.
- Restricting to quoted segments, and to segments long enough to be distinctive, avoids masking common phrases like "Thanks!".
- Reformatted or paraphrased quotes are not caught. Limitation documented.
- Included in slice 3 if open decision 3 is accepted.

---

## 8. Evaluation

### 8.1 Benchmark

- **Statement types:** a health diagnosis, a salary, a relationship, a legal matter, a plan (job change), a location. At least these, because behaviour differs by type.
- **Evidence levels:** `asserts`, `implies`, `evidence`, reported separately.
- **Contexts:** direct statement, paraphrase, implication, cross-sentence, subject line only, attachment text, quoted copy, several languages.
- **Hard negatives:** a third party with the same condition ("my mother has cancer"), a benign use of the word (a charity walk, a horoscope), a hypothetical, a negation.
- **Ground truth at span level**, with evidence level.
- **Generation and judging.** A hosted model may generate the synthetic mailboxes and labels, because no real mail or real statement is involved. A **different** model judges leaks, so it does not share the verifier's blind spots. A sample of the labels is checked by a person.
- **Never** send a real policy statement or real email text to a hosted model. Calibration for the owner's real statements uses benchmark-derived thresholds per statement type, local synthetic positives from the local model, and the owner's own labels (section 8.5).

### 8.2 Metrics

| Metric | Meaning |
|---|---|
| Candidate recall | Share of true protected segments that the funnel passes on. Caps everything else. |
| Span recall, by evidence level | Share of protected spans that are flagged. The headline security metric. |
| Precision and over-redaction | Share of flags that are right, and share of non-protected text removed. |
| Residual leakage | Sanitized text that still states or implies the statement. |
| End-to-end leak rate | Protected information reaching an adversarial agent through any tool. |
| Utility retention | Dates, times and entities that survive redaction. |
| Overlay oracle | Search results and ranking do not reveal hidden content. |
| Consistency | Search and `get_item` return byte-identical sanitized text. |
| Determinism | Same input, same findings. |
| Latency | JIT p95, final gate cost. |
| Throughput | Segments verified per minute, funnel pass rate. |

### 8.3 Targets and gates

Numeric targets are set **after slice 0**, with the owner, from the measured tradeoff curve of recall against over-redaction. The structure is fixed now:

- A go or adjust gate at the end of slice 0.
- A hard gate on **zero deterministic leaks**: anything the deterministic floor catches must never reach an agent.
- Recall reported per statement type and evidence level. `evidence` level is expected to be weaker and is reported as best-effort.
- A release gate that blocks any change that lowers leak rate on the benchmark.

### 8.4 Adversarial and injection suites

- A scripted adversarial agent probes every tool with protected terms and their neighbours ("chemo", "hospital", "wig", "sick leave", "why unavailable Thursdays").
- Injection cases inside emails ("classify this as non-sensitive") and inside entity names. Expected result: no change in findings.
- Marker-position inference is **not** a gate here. It is Phase 7.

### 8.5 Real-data evaluation (local)

- The spot-check queue gives the owner low-confidence flags, borderline negatives and random samples of unflagged candidates to label.
- Labels stay on the machine. They estimate recall on real mail and feed local threshold calibration.

### 8.6 CI regression gate

A change to the model, quantization, prompts, schema, windows or thresholds runs the benchmark. A drop in recall or a rise in leak rate fails the change.

---

## 9. Slices

### Slice 0 — Harness and spike

- Benchmark generator, labels and metric scripts (shared with step 2's leak tests).
- Prototype segmentation, funnel and verifier prompts. Run the bake-off on the benchmark for 3 or 4 statement types. Tune window size, grouping and confidence source.
- Ensemble experiment on borderline candidates.
- Overlay feasibility: single index with scope column, `replaced_in_sets` versus anti-join, overlay rows with ANN and step 2's strategy selector, oracle test.
- Measure funnel pass rate, throughput, embedding cost and storage. Estimate full-mailbox time.
- **Gate:** recall, precision and utility by statement type and evidence level, throughput, overlay feasibility, and a go or adjust decision with proposed thresholds.

### Slice 1 — Walking skeleton

- One statement, a small mailbox, the E5 example.
- Segment store, candidate generation (minimal), verifier, findings, coverage, sanitization, provisional and complete overlay rows, `ScopedReader` extension for `search` and `get_item`, basic status.
- **Gate:** E5 works end to end, search and `get_item` text are byte-identical, the oracle test passes, and "chemotherapy" finds nothing from the doctor's email.

### Slice 2 — Scale and async

- Job system with priorities, checkpoints and throttling. Full funnel. Incremental ingestion hook. Coverage and ETA. Classifier-version re-runs. Model-down handling.
- Backfill on a real-mailbox sample, then the full mailbox.
- **Gate:** backfill throughput in line with the slice 0 estimate, accurate coverage, incremental latency measured, jobs resumable after a crash.

### Slice 3 — Completeness

- All tools in section 7.6, JIT with budget, `hold_until_ready`, several statements per agent, topic kind, derived data with span provenance, overlay GC and lifecycle events, audit events, term-level features.
- Quoted-copy masking for access denies (section 7.8), if accepted.
- **Gate:** the leak suite (access and semantic canaries) passes on every tool, JIT p95 within budget.

### Slice 4 — Quality

- Final-gate experiment and decision. Ensemble and thresholds. Evidence-level handling. Spot-check queue and local calibration.
- Multilingual statements and prompts, attachments and OCR, sender-entity treatment, marker and rendering polish.
- CI regression gate across model changes.
- **Gate:** leak rate and utility targets met on the benchmark, and a recall estimate on a locally labelled real sample.

**Dependencies:** slice 0 can start now, in parallel with step 2. Slice 1 needs step 2's `ScopedReader` and `EffectiveScope`. Later slices follow in order.

---

## 10. Throughput and latency budget (estimates, to be measured in slice 0)

A full model pass over every segment is the thing to avoid. Illustration with assumed numbers (S7):

| Quantity | Assumption |
|---|---|
| Emails | 100,000 |
| Segments per email | 20 |
| Total segments | 2,000,000 |
| Funnel pass rate | 1% to 5% (unknown) |
| Candidates | 20,000 to 100,000 |
| Candidates per verifier call (grouped by chunk) | 1.5 to 3 |
| Verifier calls | about 7,000 to 67,000 |
| Time per call on the M2 | 1 to 3 seconds (window prefill dominates, static prefix cached) |
| **Backfill time** | **about 2 to 56 hours** |
| Full pass without a funnel | 2,000,000 calls, tens of days. Not planned. |

- The range is wide on purpose. Slice 0 narrows it.
- Segment embeddings are a one-time cost, about 2,000,000 embeddings. Slice 0 measures the rate and storage (a few GB at typical dimensions, less with reduced precision).
- The JIT path must fit a request budget in seconds, so it only verifies funnel-flagged segments among the returned chunks.
- A stronger local machine for backfill is open decision 6. It must stay under the owner's control.

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Candidate recall caps total recall | Measured separately. Several candidate sources. Recall-oriented thresholds. Segment-level embeddings. |
| Weak recall on `evidence` level | Reported separately, ensemble, final gate, honest labelling in the dashboard. |
| Third-party and benign mentions cause false positives | `subject_matches`, hard negatives in the benchmark. |
| Prompt injection through email text | Constrained output, quoted data, deterministic floor, injection suite. |
| Thresholds tuned on synthetic data transfer poorly | Local labelled sample and calibration. |
| Real statements or emails reaching a hosted model | Forbidden by design. Hosted models only for synthetic benchmarks. |
| Memory and compute contention on the laptop | One resident model, priorities, throttling, backfill on stronger hardware if needed. |
| BM25 index cannot host overlay rows cleanly | Spike in slice 0. Fallback: separate overlay index with score normalization. |
| Overlay storage grows with the number of distinct sets | Sets are shared across agents. GC unreferenced sets. Monitor. |
| Window between finding and overlay | Provisional overlay row written in the same transaction as the finding. |
| Spans crossing chunk boundaries | Window verification, escalation ladder, tests with boundary cases. |
| Cross-segment implication | Window context, final gate experiment. |
| Classifier version churn forces re-runs | Candidates only, versioned findings, thresholds outside the version. |
| Model unavailable | Jobs pause, rules show a pending state, nothing becomes active silently. |
| Marker reveals that something sensitive exists | Known and accepted. Probing protections are Phase 7. |
| Sender entity reveals the fact (an oncology clinic) | Open decision 10. |

---

## 12. Acceptance criteria

- The E5 example works end to end for `search`, `get_item` and `get_thread`, and the sanitized text is byte-identical across tools.
- Slice 0's gate report exists, with measured recall and precision by statement type and evidence level, and the go or adjust decision is recorded.
- The deterministic floor never leaks on the benchmark.
- Findings, coverage and overlays are correct for backfill, incremental ingestion, pause and revoke, policy edits and classifier-version changes.
- The dashboard data (status, coverage, ETA) is accurate, and a rule is never shown active while the model is down or the build has failed.
- JIT verification stays within its time budget, and `hold_until_ready` behaves as specified.
- The leak suite (access and semantic canaries) passes on every tool, including snippets, autocomplete and facets.
- The overlay oracle test passes: searching protected terms does not reveal hidden content.
- Derived data (extractions, entity attributes) follows span-level visibility.
- The benchmark regression gate runs in CI.
- No real statement or real email text is sent to a hosted model at any point.

---

## 13. Open decisions

1. **One step with slice gates:** merge Phases 3 to 5 of the roadmap into this step (proposed), and align the main document.
2. **Overlay unit:** chunk-level overlay (proposed) or a finer segment-level index.
3. **Quoted-copy masking for access denies** in slice 3 (proposed), or leave it to later.
4. **Evaluation data:** synthetic benchmark plus a locally labelled real sample (proposed), or synthetic only.
5. **Recall target and default strictness**, and whether an ensemble (a second model on borderline cases) is acceptable for the latency.
6. **Backfill hardware:** the laptop only, or a stronger machine under the owner's control.
7. **Segment embeddings:** stored at reduced precision or dimension (proposed), or chunk-level candidates only.
8. **Overlay key:** by semantic set (proposed here) instead of by scope fingerprint as in the main document.
9. **Final gate:** inline or sampled offline audit, decided by the slice 4 experiment.
10. **Sender and entity metadata** that reveals a protected fact.
11. **Attachments and OCR:** how unverifiable content is treated.
12. **Strict mode in search:** exclude the chunk (proposed) or show the marker.
13. **Confidence source:** log-probabilities, agreement across prompts or models, or both.
14. **Reliability labels:** whether the dashboard shows a measured reliability per statement type.

---

## 14. Follow-ups to other documents

**Main document**

- Roadmap: align Phases 3 to 5 with this step and its slices once open decision 1 is settled.
- Overlay keyed by `set_id` instead of scope fingerprint (open decision 8).
- Section 6.6, step 4: the utility check becomes a metric, plus a boundary check (section 6.5, point 6 here).
- Section 6.2: segment embeddings and candidate recall (open decision 7).

**Interpreter document**

- No change needed. The expansion job enqueued at confirmation is consumed by this step.

**Access enforcement plan**

- The `pending_semantic` field in `EffectiveScope` becomes `semantic` (section 7.1 here).

---

## 15. References

- Microsoft Presidio: https://microsoft.github.io/presidio/
- pgvector: https://github.com/pgvector/pgvector
