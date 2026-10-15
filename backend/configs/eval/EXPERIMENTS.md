# Experiments

Controlled experiments over the shared `SearchPipeline`, run through the
`rosalind` CLI against a backend **in eval mode** (see `docs/eval.md`).

Each experiment is a single YAML under `configs/eval/experiments/`:

```bash
# server: dev stack (`just dev`); eval enabled via ROSALIND_EVAL__ENABLED=true in .env
rosalind eval run --config configs/eval/experiments/fusion-convex-a0.5.yaml
```

Every run writes comparable artifacts under the eval `runs_dir`. Compare two
runs (deltas + paired bootstrap CI + permutation p-value):

```bash
rosalind eval runs
rosalind eval compare <runA> <runB>
```

## Retrieval experiments

| Experiment | Config | Judged by |
|---|---|---|
| Mode | `mode-lexical.yaml`, `mode-semantic.yaml`, `mode-hybrid.yaml` | recall@fused_k, MRR/nDCG@10 |
| Fusion | `fusion-rrf-k60.yaml` vs `fusion-convex-a0.5.yaml` | recall@fused_k |
| Reranker | `rerank-off.yaml` vs `rerank-k20/k40/k60.yaml` | nDCG@10 / MRR of the final order |
| Rerank text | `rerank-display-text.yaml` (prefix off) | nDCG@10 |
| Per-message cap | `cap-1.yaml`, `cap-2.yaml`, `cap-3.yaml`, `cap-none.yaml` | recall@fused_k, diversity |

RRF uses ranks only (zero-shot safe). The convex combination min-max normalizes
BM25, uses cosine similarity as is, counts a missing branch as 0, and weights the
semantic side with `convex_alpha`. Tune `convex_alpha` on the dev split.

## Environment-driven experiments

Two experiments change the index or the retriever wiring, so they are set via
the backend YAML/env before starting the server, not as plan overrides:

- **Embedding model comparison** (`ROSALIND_EMBEDDING_SPACE`): selects the
  embedding space. This requires that space's column and partial HNSW index to
  be populated by the ingestion/embedding pipeline first; it does not rebuild
  other indexes (embeddings are inline `emb_<space>` columns).
- **ANN vs exact** (`ROSALIND_SEARCH_SEMANTIC_EXACT_THRESHOLD`): forces the exact
  path versus HNSW for filtered queries. Run the same dataset twice, then
  compare; per-question `semantic_filter_path` (`exact` / `ann_iterative`) and
  `semantic_scan_limit_hit` are stored in `questions.parquet`.

## Caching (`--cache-dir`)

Eval keeps a per-stage cache keyed by stage-specific inputs, so changing a
downstream stage never recomputes upstream work: lexical depends on
scope/filters/lexical query/`lexical_k`; semantic adds the query vector's
model/version and `semantic_k`; fused adds the fusion config; reranked adds the
reranker version, `rerank_k` and the rerank text mode. Set it via the backend
eval config (`eval.runs_dir` holds `_cache/`).
