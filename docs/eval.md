# Evaluation (`rosalind eval`)

Rosalind's search evaluation runs **inside the backend**, behind an
eval-mode gate, and is driven by the `rosalind` CLI. Eval reuses the production
`SearchPipeline`; it never reimplements search and never requires a separate
application.

## Eval mode

Eval is off by default. Enable it in the backend config (YAML or env):

```yaml
# rosalind.yaml
eval:
  enabled: true
  runs_dir: runs
```

Equivalent env: `ROSALIND_EVAL__ENABLED=true`, `ROSALIND_EVAL__RUNS_DIR=…`.

When enabled, the backend mounts the `/eval` HTTP routes; when disabled they do
not exist (the modules are never imported). **Enable eval only against a
throwaway test database** (ParadeDB + pgvector, migrated).

## Eval stack

The justfile runs eval against its **own** Postgres, object storage, and
Keycloak — a separate Compose project (`rosalind-eval`) with its own volumes —
but on the **same host ports** as dev, so the backend and CLI need no
environment-specific configuration. The two stacks are therefore mutually
exclusive: stop one before starting the other.

| Service | Endpoint |
|---|---|
| Postgres (ParadeDB) | `localhost:5432` (`rosalind_eval` DB) |
| SeaweedFS S3 | `http://localhost:8333` |
| Keycloak | `http://localhost:8080` |
| Backend API | `http://localhost:8000` |

```bash
just eval-up        # start eval Postgres + SeaweedFS + Keycloak (project rosalind-eval)
just eval-migrate   # apply migrations to the eval database
just eval-dev       # eval-up + ml deps + eval-migrate + eval backend on :8000 (eval mode on)
just eval-serve     # just the eval backend (ROSALIND_EVAL__ENABLED=true)
just eval-logs      # tail eval infrastructure logs
just eval-down      # stop eval infrastructure (keep volumes)
just eval-reset     # wipe only the eval project volumes (dev volumes untouched)
```

The CLI needs no configuration: `rosalind` defaults to these endpoints, so the
same command works in dev and eval mode. (Optional: the CLI reads a YAML config
file and `--profile` for pointing at other hosts — see the CLI README.) Stop the
eval backend/infra (`just eval-down`) before starting the dev stack (`just dev`),
and vice versa.

Typical run:

```bash
just eval-dev
rosalind auth login
rosalind import create --source google /path/to/Mail
rosalind index <import_id>
rosalind eval items --import <import_id>            # key gold manually
rosalind eval run --config backend/configs/eval/experiments/mode-hybrid.yaml
rosalind eval compare <runA> <runB>
just eval-reset
```

The eval Compose file is `docker-compose.eval.yml`; it reuses
`keycloak/rosalind-realm.json` in a second Keycloak instance, so you may need to
`rosalind auth login` again after switching between dev and eval.

## Dependency rule

Eval lives under the normal hexagonal layers — `application/eval/`
(pure logic, models, config, ports), `application/services/eval.py` (use cases),
`adapters/outbound/eval/` (search executor, Parquet run store, item catalog,
Ollama, mailbox source, stage cache), and `adapters/inbound/http/routes/eval.py`
+ `schemas/eval.py`. **No production module imports eval**; the only references
are the composition root and the gated include in the app factory. Enforced by
`tests/unit/test_eval_imports.py`.

Optional dependencies (`ranx`, `pyarrow`, `duckdb`, `instructor`) live in the
backend `eval` dependency group, which `dev` includes.

## Workflow

1. **Run Rosalind in eval mode** (`just eval-dev`) against the throwaway eval DB.
2. **Import data as normal** — no eval-specific importer:
   `rosalind import create …` then `rosalind index <import_id>`
   (including `embed` for semantic/hybrid).
3. **Key gold manually.** List imported items and their ids, then write a JSONL
   dataset referencing those ids:
   ```bash
   rosalind eval items --import <import_id>
   ```
   Dataset JSONL record (gold uses canonical `item_id`, optional attachment
   evidence):
   ```json
   {"id":"q_001","type":"amount_lookup","query":"how much did the roofer quote?",
    "gold":[{"item_id":"<uuid>"}],"answer":"$8,400","split":"dev","status":"reviewed"}
   ```
4. **Validate and run:**
   ```bash
   rosalind eval validate-dataset datasets/dev.jsonl --known-item-ids ids.json
   rosalind eval run --config configs/eval/experiments/mode-hybrid.yaml
   rosalind eval runs
   rosalind eval compare <runA> <runB>
   ```

## CLI commands

- `rosalind eval run --config <yaml>` — stream per-question progress, then a
  metrics summary.
- `rosalind eval runs` — list runs.
- `rosalind eval compare <A> <B>` — paired metric deltas with 95% CI and p-value.
- `rosalind eval validate-dataset <path> [--known-item-ids <json>]`.
- `rosalind eval generate-questions --mailbox <mbox> --output <jsonl>` — draft
  questions via a local Ollama model (optional `eval` deps).
- `rosalind eval items [--import <id>]` — list keyable item ids.

## Run storage

Each run is written under `eval.runs_dir/<run_id>/`:

```text
manifest.json       run id, git commit, config, dataset hash, versions, times
questions.parquet   per-question metrics, funnel, versions, timings
stage_hits.parquet  per-stage candidates (chunk/item id, rank, score)
metrics.json        overall + slices + funnel counts + latency percentiles
events.jsonl        structured event log (run_id/question_id on every line)
```

Run data is never written to the production database.
