"""`rosalind eval ...` commands.

These talk to the backend's ``/eval`` surface, which exists only when the server
runs in eval mode. The CLI stays a pure HTTP client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from cli import output
from cli.client import ApiClientError
from cli.client import eval as client
from cli.output import json as json_output
from cli.output import tables

eval_app = typer.Typer(
    help="Search evaluation (requires the server to run in eval mode)."
)

_CONFIG_OPTION = typer.Option(
    ...,
    "--config",
    "-c",
    exists=True,
    dir_okay=False,
    readable=True,
    help="Experiment YAML config.",
)


@eval_app.command("run")
def run(
    config: Annotated[Path, _CONFIG_OPTION],
) -> None:
    """Run an experiment defined by a YAML config."""
    raw = _load_yaml(config)
    dataset_path = _resolve_dataset(config, raw)
    records = _read_jsonl(dataset_path)
    try:
        for event in client.run_experiment(raw, records):
            _render_event(event)
    except ApiClientError as exc:
        typer.echo(f"eval run failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@eval_app.command("runs")
def runs() -> None:
    """List available runs."""
    try:
        run_ids = client.list_runs()
    except ApiClientError as exc:
        typer.echo(f"failed to list runs: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if output.json_mode:
        json_output.render_json(run_ids)
        return
    for run_id in run_ids:
        typer.echo(run_id)


@eval_app.command("compare")
def compare(
    run_a: Annotated[str, typer.Argument(help="First run id.")],
    run_b: Annotated[str, typer.Argument(help="Second run id.")],
) -> None:
    """Compare two runs (metric deltas with confidence intervals)."""
    try:
        deltas = client.compare(run_a, run_b)
    except ApiClientError as exc:
        typer.echo(f"failed to compare runs: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(deltas)
        return

    headers = ("METRIC", "A", "B", "DELTA", "95% CI", "P")
    rows = []
    for delta in deltas:
        ci = _format_ci(delta.get("ci_low"), delta.get("ci_high"))
        p_value = delta.get("p_value")
        rows.append(
            (
                delta["metric"],
                f"{delta['a']:.3f}",
                f"{delta['b']:.3f}",
                f"{delta['delta']:+.3f}",
                ci,
                f"{p_value:.3f}" if p_value is not None else "-",
            )
        )
    tables.render_table(headers, rows)


@eval_app.command("validate-dataset")
def validate_dataset(
    dataset: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    known_item_ids: Annotated[
        Path | None,
        typer.Option(
            "--known-item-ids",
            exists=True,
            dir_okay=False,
            readable=True,
            help="JSON list of item ids in the corpus.",
        ),
    ] = None,
) -> None:
    """Validate a JSONL dataset against the eval corpus."""
    records = _read_jsonl(dataset)
    known = _read_known_item_ids(known_item_ids) if known_item_ids else None
    try:
        issues = client.validate_dataset(records, known_item_ids=known)
    except ApiClientError as exc:
        typer.echo(f"failed to validate dataset: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    errors = [issue for issue in issues if issue["level"] == "error"]
    if output.json_mode:
        json_output.render_json(issues)
    else:
        for issue in issues:
            typer.echo(
                f"[{issue['level']}] {issue['code']}: {issue['message']}"
                + (f" ({issue['question_id']})" if issue.get("question_id") else "")
            )
        typer.echo(f"{len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
    if errors:
        raise typer.Exit(code=2)


@eval_app.command("generate-questions")
def generate_questions(
    mailbox: Annotated[
        Path, typer.Option("--mailbox", exists=True, dir_okay=False, readable=True)
    ],
    output_path: Annotated[Path, typer.Option("--output", "-o", dir_okay=False)],
    split: Annotated[str, typer.Option("--split")] = "dev",
    include_trash_spam: Annotated[bool, typer.Option("--include-trash-spam")] = False,
) -> None:
    """Write draft questions from a mailbox using the server's local LLM."""
    try:
        records = client.generate_questions(
            str(mailbox), split=split, include_trash_spam=include_trash_spam
        )
    except ApiClientError as exc:
        typer.echo(f"failed to generate questions: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    typer.echo(f"wrote {len(records)} draft questions to {output_path}")


@eval_app.command("items")
def items(
    import_id: Annotated[
        str | None, typer.Option("--import", help="Scope to one import.")
    ] = None,
) -> None:
    """List keyable corpus item ids for manual gold authoring."""
    try:
        rows = client.list_items(import_id)
    except ApiClientError as exc:
        typer.echo(f"failed to list items: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(rows)
        return

    headers = ("ITEM_ID", "DATE", "FROM", "SUBJECT")
    table_rows = [
        (
            row["item_id"],
            (row.get("occurred_at") or "-")[:10],
            row.get("sender") or "-",
            (row.get("subject") or "-")[:60],
        )
        for row in rows
    ]
    tables.render_table(headers, table_rows)


def _render_event(event: dict[str, Any]) -> None:
    if output.json_mode:
        typer.echo(json.dumps(event))
        return
    kind = event.get("event")
    if kind == "run.start":
        typer.echo(f"run {event['run_id']} ({event['questions']} questions)")
    elif kind == "question.done":
        status = "hit" if event.get("hit") else event.get("funnel") or "miss"
        typer.echo(f"  {event['question_id']}: {status}")
    elif kind == "run.complete":
        typer.echo("")
        typer.echo(f"run complete: {event['run_id']} -> {event.get('location', '')}")
        overall = event.get("metrics", {}).get("overall", {})
        for key, value in overall.items():
            if isinstance(value, float):
                typer.echo(f"  {key}: {value:.3f}")
        for warning in event.get("warnings", []):
            typer.echo(f"  warning: {warning}")


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        typer.echo(f"{path}: config must be a mapping", err=True)
        raise typer.Exit(code=2)
    return raw


def _resolve_dataset(config_path: Path, raw: dict[str, Any]) -> Path:
    dataset = raw.get("dataset")
    if not dataset:
        typer.echo(f"{config_path}: config has no 'dataset'", err=True)
        raise typer.Exit(code=2)
    path = Path(dataset)
    if not path.is_absolute():
        path = config_path.parent / path
    if not path.is_file():
        typer.echo(f"dataset not found: {path}", err=True)
        raise typer.Exit(code=2)
    return path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            typer.echo(f"{path}:{line_number}: invalid JSON: {exc}", err=True)
            raise typer.Exit(code=2) from exc
    return records


def _read_known_item_ids(path: Path) -> list[str]:
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        raw = raw.get("item_ids", [])
    if not isinstance(raw, list):
        typer.echo(f"{path}: expected a list of item ids", err=True)
        raise typer.Exit(code=2)
    return [str(item) for item in raw]


def _format_ci(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "-"
    return f"[{low:.3f}, {high:.3f}]"
