# Experiments

Controlled experiments over the shared `SearchPipeline`. Each experiment is a
single YAML under `configs/experiments/`; run it against a populated eval corpus:

```bash
rosalind-eval run --config configs/experiments/fusion-convex-a0.5.yaml \
  --database-url "$ROSALIND_DATABASE_URL" --account-id <uuid> \
  --runs-dir runs --cache-dir runs/_cache
```

Every run writes a comparable artefact under `runs/<run_id>/`. Compare two runs
(deltas + paired bootstrap CI + permutation p-value):

```bash
rosalind-eval compare runs/<runA> runs/<runB>
```

## Caching (`resume_from`)

`--cache-dir` enables the stage cache. Keys are per stage, so changing a
downstream stage never recomputes upstream work: lexical depends on
scope/filters/lexical query/`lexical_k`; semantic adds the query vector's
model/version and `semantic_k`; fused adds the fusion config; reranked adds the
reranker version, `rerank_k` and the rerank text mode. For example, changing only
the fusion strategy reuses the cached lexical and semantic results and reruns
from fusion onward.

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

Two experiments are not expressible as plan overrides because they change the
index or the retriever wiring; set environment variables before `run` (they are
read when the service is built):

- **Embedding model comparison** (`ROSALIND_EMBEDDING_SPACE`): selects the
  embedding space (e.g. `bge_m3_v1`). This requires that space's column and
  partial HNSW index to be populated by the ingestion/embedding pipeline first;
  it does not rebuild other indexes. In this codebase embeddings are inline
  `emb_<space>` columns (see `docs/features/emails.md`), so a new model needs its
  own column + index before it can be compared.
- **ANN vs exact** (`ROSALIND_SEARCH_SEMANTIC_EXACT_THRESHOLD`): forcing the
  exact path versus HNSW for filtered queries. Run the same dataset twice (exact
  vs ANN), then compare; per-question `semantic_filter_path` (`exact` /
  `ann_iterative`) and `semantic_scan_limit_hit` are stored in
  `questions.parquet` to report where the ANN scan stopped early.
