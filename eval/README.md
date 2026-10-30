# Eval bundles

Eval source files are grouped per **bundle**: one corpus with its gold labels
and experiment configs, kept together so a benchmark can be reproduced and
compared without hunting across the tree.

```
eval/<bundle>/
  corpus.mbox           # the emails: import + generate-questions source
  dataset.jsonl         # gold, message_id-keyed
  experiments/*.yaml    # dataset: ../dataset.jsonl
  NOTES.md              # optional: provenance (provider, account, dates)
```

A bundle is **not** a run: each experiment YAML produces one run against the
bundle's dataset. The CLI resolves each YAML's `dataset:` relative to the YAML
itself, so every experiment references the shared gold as `../dataset.jsonl`.

## Git policy

Bundles are **private by default**; the root `.gitignore` ignores every
`eval/*/` directory. Only bundles whose directory name ends in `-synthetic` are
tracked. Commit a bundle (mbox included) only when it is synthetic/shareable —
never real personal mail.

```
eval/email-rag-synthetic/   # committed (synthetic)
eval/inbox-2026/            # local only (real mail)
```

## Workflow

Run against the dev stack (`just dev`; eval is enabled via `.env`). Replace
`<bundle>` with the bundle directory:

```bash
rosalind import create --source google eval/<bundle>/corpus.mbox
rosalind index <import_id>
rosalind eval items --import <import_id>            # key gold manually
rosalind eval generate-questions --mailbox eval/<bundle>/corpus.mbox \
  -o eval/<bundle>/dataset.jsonl                    # optional draft
rosalind eval validate-dataset eval/<bundle>/dataset.jsonl
rosalind eval run --config eval/<bundle>/experiments/mode-hybrid.yaml
rosalind eval compare <runA> <runB>
```

Gold references either the provider `message_id` (portable across imports) or a
canonical `item_id`; `message_id` wins when both are present. See
`docs/eval.md` for the dataset format and the full command reference.

## Bundles

| Bundle | Contents |
|---|---|
| `email-rag-synthetic/` | Committed synthetic corpus; backs the eval tests. See its `EXPERIMENTS.md`. |
