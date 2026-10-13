# rosalind-eval: search evaluation implementation plan

Instructions for a coding agent. Work through the phases in order.

## Context

Rosalind is a personal data warehouse that ingests emails and exposes search to an external AI agent over MCP. The backend is Python, organized with ports and adapters. The search path is: Prepare (builds a frozen `SearchPlan`), then lexical BM25 (ParadeDB pg\_search), semantic (pgvector HNSW, bge-m3), fuse (RRF), rerank (bge-reranker-v2-m3 via a `Reranker` port), then Assemble. The design doc `emails.md` describes each stage and its output types (`LexicalResult`, `SemanticResult`, `FusedCandidates`, `RerankResult`).

Goal: build **rosalind-eval**, a tool to audit and optimize each pipeline stage with controlled experiments, and refactor the app so that serving and auditing share one orchestrator.

## Principles

1. **One pipeline.** The orchestrator lives in the app (`rosalind`). The eval package imports it and never reimplements it.
2. **Dependency direction.** `rosalind-eval` depends on `rosalind`. Production code must never import the eval package.
3. **Local only.** No email content may leave the machine. No SaaS tracing or evaluation services. Any LLM used for question generation or judging must be a local model (Ollama) unless the code path only touches the synthetic fixture mailbox.
4. **Gold labels use `item_id`** (plus an optional attachment `blob_sha256`), never `chunk_id`. Chunk IDs change when chunking changes.
5. **No change to the external MCP surface** (tool names, input schemas, response shapes) unless explicitly asked. Stage overrides go through an internal API, not tool parameters.
6. **Behavior-preserving first.** Refactor with tests proving identical output before adding features.
7. If the repo differs from what this plan assumes, say so and adapt. Do not guess silently.

## Phase 0: Recon (no code changes)

- Read `emails.md` and the search code under `backend/src/rosalind/application/search/`, `application/services`, `application/ports`.
- Produce a short report: the actual function and class names for each stage, how they are wired together today, where the MCP adapter calls them, how config (`budgets`, versions) is loaded, how tests and the dev database are run.
- List any mismatch with this plan and propose adjustments.

**Done when:** the report is written and I have approved it.

## Phase 1: `SearchPipeline` orchestrator returning a `SearchTrace`

Refactor so one object runs the stages and returns its intermediate state as data.

```python
class SearchPipeline:
    def __init__(self, lexical, semantic, fuser, reranker, assembler): ...
    def run(self, plan, *, trace_level="minimal", resume_from=None, cached=None) -> SearchTrace: ...

class SearchTrace:
    plan: SearchPlan
    lexical: LexicalResult | None
    semantic: SemanticResult | None
    fused: FusedCandidates | None
    reranked: RerankResult | None
    response: SearchResponse   # what the MCP adapter returns today
    timings_ms: dict
```

Requirements:

- Dependencies are injected (ports), so tests and experiments can swap implementations.
- `trace_level="minimal"` (production default) keeps only IDs, scores, counts, timings and versions. `"full"` keeps everything, including candidate lists.
- `resume_from` (one of `lexical`, `semantic`, `fuse`, `rerank`, `assemble`) plus `cached` lets a caller re-run from a stage using stored upstream results.
- The MCP adapter calls `run(plan)` and returns `trace.response`.
- Production persists only a minimal trace summary (plan fingerprint, versions, counts, timings, chunk IDs). Full traces are never stored by default.
- Stage overrides (reranker, `rerank_k`, fusion strategy, fusion parameters) are accepted only through the internal API, never through MCP tool parameters.

**Done when:**

- A regression test runs a fixed set of queries against a fixture database before and after the refactor and shows byte-identical `SearchResponse` output.
- Unit tests cover `resume_from` for every stage.
- The public MCP schema is unchanged (snapshot test).

## Logging (implement with Phase 1; applies to every later phase)

Logging is structured, local, and content-free by default, and it builds on `SearchTrace`. Nothing is shipped to an external service.

**Setup**

- Use the logging library the repo already uses. If there is none, use stdlib `logging` with a small in-repo JSON formatter. Do not add a dependency without asking.
- Config keys: `log_level`, `log_format` (`console` for dev, `json` for deployed, written to stdout).
- Correlation fields on every event, carried with `contextvars`: `request_id`, `audit_id`, `account_id`, `plan_fingerprint`, and `stage`. Eval runs add `run_id` and `question_id`.

**Search: one summary event per request (INFO)**

- `plan_fingerprint`, `mode_requested`, `mode_effective`, `strategy`, and the version stamps (index, embedding model and version, reranker).
- Filter names used and list sizes, never filter values (they contain email addresses).
- Per stage: hit or candidate counts, `dropped_by_item_cap`, `exhausted`, `complete`, `filter_path`, `scan_limit_hit`, `applied` for the reranker, and `elapsed_ms`.
- Result count, warning codes, and whether the request was degraded (for example a fallback to lexical when embedding is unavailable).
- Per-stage detail events go at DEBUG, off by default.

**Never log, at any level by default:** query text, keywords, subjects, bodies, snippets, email addresses or names, query vectors. Chunk IDs and item IDs are allowed. A `log_query_text` flag may exist for local development only, off by default, and it must log a warning at startup when enabled.

**Persistence**

- Reuse the existing audit mechanism (`audit_id`) if Phase 0 finds one; otherwise add a small `search.request_log` table holding the minimal trace summary from Phase 1: the fields above plus the returned chunk IDs.
- Retention is configurable (default 30 days), and rows are deleted when the account's data is deleted.
- Replaying a production query needs its `SearchPlan`, which contains query text. Provide an opt-in capture mode that stores plans separately; it is off by default, and its privacy cost is documented in the config reference.

**Ingestion (offline pipeline)**

- Per record and stage: `stage`, `stage_version`, input hash or ID, outcome (`ok`, `skipped_unchanged`, `failed`), `elapsed_ms`, parser warnings, and error type on failure. No content.
- One summary event per archive run: counts per stage of ok, skipped and failed, and total duration.

**Evaluation runs**

- Each run writes a manifest: `run_id`, git commit, config, dataset hash, index and model versions, compute backend (MPS or CPU), start and end time.
- Each run also writes a structured event log with `question_id` on every event, kept next to the Parquet results.
- Console output (Rich) is separate from the log file. At the end of a run, print a summary of warnings, such as gold items missing from the index.

**Done when**

- A test runs searches on the fixture mailbox with log capture and asserts that no query text, keyword, address or email text appears in any record at any level, except when `log_query_text` is explicitly enabled.
- Every search request produces exactly one summary event containing the required fields, and every event in a request carries the same `request_id`.
- An ingestion run on the fixture archive logs per-stage ok, skipped and failed counts, and re-running it logs `skipped_unchanged`.
- An eval run produces a manifest and an event log.

## Phase 2: Scaffold `rosalind-eval`

- Separate package in the repo (own `pyproject.toml`, dev dependency on `rosalind`). Python package `rosalind_eval`.
- CLI with Typer and Rich: `rosalind-eval run --config <yaml>`, `rosalind-eval compare <runA> <runB>`, `rosalind-eval validate-dataset`.
- Experiment configs are YAML: dataset, pipeline overrides (`rerank_k`, reranker on or off, fusion strategy and parameters, `lexical_k`, `semantic_k`, `fused_k`, chunk prefix on or off, mode), and a name.
- pytest set up. Lint and type checks consistent with the main repo.

**Done when:** `rosalind-eval --help` works, a no-op config loads and validates, and CI runs the empty test suite.

## Phase 3: Dataset format and fixture mailbox

JSONL, one record per question:

```json
{"id": "q_042", "type": "amount_lookup",
 "query": "how much did the roofer finally quote?",
 "keywords": null,
 "filters": {"date_from": "2026-01-01"},
 "gold": [{"item_id": "e_9f2c", "evidence": "attachment:e5a1..."}],
 "answer": "$8,400", "answerable": true, "split": "dev", "status": "reviewed"}
```

- Question types: `factual`, `amount_lookup`, `exact_token` (invoice numbers, IDs), `filter_heavy`, `attachment_only`, `thread`, `multi_hop`, `unanswerable`, `aggregation` (checked for tool routing only, not retrieval metrics).
- Validation: schema check, every `item_id` exists in the target database, dev and test splits do not overlap, `unanswerable` has empty `gold`.
- Dataset files must contain `item_id`s, not email bodies, so they can be versioned in git.
- Build a **synthetic fixture mailbox** (about 50 to 100 emails, including the roof-quote example from the design doc, with an attachment, a quoted reply chain, a signature and a disclaimer, a forwarded message, a trashed email) so CI can run without private data.
- Draft-question generator: from `derived.extraction` and item metadata, use a local LLM through Instructor to write natural questions whose answer is a known item. Output status `draft`. Nothing counts toward metrics until reviewed.

**Done when:** `rosalind-eval validate-dataset` passes on the fixture dataset, and the generator produces draft questions from the fixture mailbox.

## Phase 4: Runner, metrics and run storage

- The runner calls `SearchPipeline.run(plan, trace_level="full")` for every question.
- Map retrieved chunks to gold evidence by item (and attachment blob when specified). If gold evidence includes a text span, match by span overlap.
- Metrics via **ranx** (or `ir_measures`): recall@k for the lexical branch, the semantic branch, the fused list (at `fused_k`), and the reranked list; MRR and nDCG@10 for the final order; hit rate; for unanswerable questions, rate of results returned above a score threshold.
- **Failure funnel** per failed question, one label each: not in corpus or parse failure, not chunked, missed by both branches, lost in fusion (including `dropped_by_item_cap`), lost in rerank, lost in assembly (budget, dedupe).
- Slices by question type and by which branch found the gold item (lexical only, semantic only, both).
- Statistics: paired bootstrap confidence intervals and paired significance tests for run comparisons (ranx provides these).
- Run storage: Parquet files under `runs/<run_id>/` (config, per-question results, per-stage ranks and scores, timings, versions, plan fingerprints), queried with DuckDB. Do not write eval data into the production database.
- Record p50 and p95 latency per stage.

**Done when:** `rosalind-eval run` on the fixture dataset produces a report with per-stage metrics, a funnel breakdown and slices, and `rosalind-eval compare` shows deltas with confidence intervals between two runs.

## Phase 5: Experiments

Use caching and `resume_from` so changing a downstream stage never recomputes upstream work. Cache key: (plan fingerprint, stage versions).

Implement and document these experiment configs:

- Mode: lexical vs semantic vs hybrid.
- Fusion: RRF with k=60 versus convex combination (min-max normalized BM25, cosine as is, missing counts as 0). Tune the weight offline with ranx on the dev split. Judge by recall@`fused_k`.
- Reranker: off vs on, `rerank_k` of 20, 40, 60, chunk text with and without the contextual prefix.
- Per-message chunk cap: 1, 2, 3, none.
- Embedding model comparison using the per-model partial HNSW indexes (no rebuild of other indexes).
- **ANN vs exact:** for filtered queries, compare HNSW results against the exact path and report recall loss, using `filter_path` and `scan_limit_hit` from `SemanticResult`.

**Done when:** each experiment runs from a single YAML and writes a comparable run, and the cache demonstrably skips upstream work (assert in a test).

## Phase 6: Invariant tests (pytest, pass or fail)

- Account scope isolation: account A can never retrieve account B's items through any filter combination.
- Trash and spam excluded by default, including Apple Mail folders; included only when `include_trash_spam` is true.
- Address normalization is idempotent and identical in canonicalization and in Prepare.
- `applied_filters` echoes exactly the filters used.
- `fuse` is deterministic for identical inputs (the sort rules in the design doc).
- Cursor paging returns a stable, non-overlapping sequence for a fixed plan.

**Done when:** the suite runs in CI against the fixture mailbox.

## Phase 7: Streamlit UI (localhost only)

Three pages, reading Parquet runs through DuckDB:

1. **Run comparison:** metrics by question type with confidence intervals, deltas between two runs, latency.
2. **Failure browser:** select a failed question and see the funnel step by step, with chunk text, lexical rank, semantic rank, fused rank, rerank rank and scores at each stage, and the applied filters.
3. **Labeling:** review draft questions, edit gold `item_id`s, mark a question as reviewed, too easy, or bad. Writes back to the dataset JSONL.

**Done when:** all three pages work against the fixture dataset and a real run.

## Phase 8: Later (do not start without approval)

- Ingestion stage evals: segmentation (new, quoted, signature, disclaimer, forwarded) and extraction precision and recall on about 100 hand-labeled emails, using the `extractor_version` and `confidence` fields.
- Agent-level evals with Inspect AI: did the agent use `find_entity`, pick sensible filters, and stop at the right time. Only against the fixture mailbox unless a local model is used.
- LLM judge: rubric-based, structured output through Instructor, calibrated against about 50 hand-labeled answers before any score is trusted.

## Working rules

- Tests with every change.
- Do not add a workflow framework (Haystack, LlamaIndex, LangChain). Plain classes with dependency injection.
- Do not add dependencies beyond: ranx (or ir\_measures), Typer, Rich, DuckDB, pandas or pyarrow, Streamlit, pytest, Instructor. Ask before adding anything else.
- When a decision is ambiguous, write down the options and ask before implementing.
