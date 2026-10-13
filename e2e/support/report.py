"""Compact JSON/Markdown report emission for an e2e RAG run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Email RAG e2e report",
        "",
        f"corpus fixture: `{payload.get('corpus_fixture')}`",
        f"import id: `{payload.get('import_id')}`",
        f"embedding space: `{payload.get('embedding_space')}`",
        "",
        "| case | query | mode | evidence in top-k | assembled | rank |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for q in payload.get("queries", []):
        for mode_result in q.get("modes", []):
            lines.append(
                f"| {q['id']} | {q['query']} | {mode_result['mode']} "
                f"| {mode_result['evidence_found']} "
                f"| {mode_result['evidence_assembled']} "
                f"| {mode_result.get('evidence_rank')} |"
            )
    lines.append("")
    lines.append("## quality metrics (hybrid)")
    lines.append("```")
    lines.append(json.dumps(payload.get("metrics", {}), indent=2, default=str))
    lines.append("```")
    path.write_text("\n".join(lines))
