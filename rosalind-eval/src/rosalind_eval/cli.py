"""``rosalind-eval`` command-line interface.

``run`` executes an experiment against a populated eval database and writes a
run under ``runs/<run_id>/``; ``compare`` reports metric deltas with confidence
intervals between two runs; ``validate-dataset`` and ``generate-questions``
support the dataset workflow.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from rosalind_eval import corpus, generate, validate
from rosalind_eval import dataset as dataset_mod
from rosalind_eval.compare import compare_runs, load_run
from rosalind_eval.config import ExperimentConfig, load_config
from rosalind_eval.executor import LiveSearchExecutor
from rosalind_eval.llm import make_ollama_llm
from rosalind_eval.runner import RunOutcome, run_experiment
from rosalind_eval.validate import ValidationIssue

app = typer.Typer(
    help="Audit and optimize the Rosalind search pipeline with controlled experiments.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
error_console = Console(stderr=True)

_CONFIG_OPTION = typer.Option(
    ...,
    "--config",
    "-c",
    exists=True,
    dir_okay=False,
    readable=True,
    help="Experiment YAML config.",
)
_RUN_DIR_ARG = typer.Argument(..., exists=True, file_okay=False, readable=True)
_DATASET_ARG = typer.Argument(
    ..., exists=True, dir_okay=False, readable=True, help="JSONL dataset file."
)
_MAILBOX_OPTION = typer.Option(
    None,
    "--mailbox",
    exists=True,
    dir_okay=False,
    readable=True,
    help="Mbox whose item ids count as the corpus (default: the fixture mailbox).",
)
_KNOWN_IDS_OPTION = typer.Option(
    None,
    "--known-item-ids",
    exists=True,
    dir_okay=False,
    readable=True,
    help='JSON list (or {"item_ids": [...]}) of item ids in the corpus.',
)
_DATABASE_URL_OPTION = typer.Option(
    None,
    "--database-url",
    help="Postgres URL of the eval corpus (default: $ROSALIND_DATABASE_URL).",
)
_ACCOUNT_ID_OPTION = typer.Option(
    None, "--account-id", help="Account UUID that owns the eval corpus."
)
_RUNS_DIR_OPTION = typer.Option(
    Path("runs"), "--runs-dir", help="Where runs are written."
)
_GEN_MAILBOX_OPTION = typer.Option(
    None,
    "--mailbox",
    exists=True,
    dir_okay=False,
    readable=True,
    help="Mbox to generate from (default: the fixture mailbox).",
)
_OUTPUT_OPTION = typer.Option(
    ..., "--output", "-o", dir_okay=False, help="Where to write the JSONL dataset."
)
_MODEL_OPTION = typer.Option("llama3.1", "--model", help="Ollama model name.")
_BASE_URL_OPTION = typer.Option(
    "http://localhost:11434/v1", "--base-url", help="Ollama OpenAI-compatible base URL."
)
_LIMIT_OPTION = typer.Option(
    None, "--limit", min=1, help="Only generate for the first N passages."
)


def main() -> None:
    """Console entry point (``rosalind-eval``)."""
    app()


@app.command()
def run(
    config: Path = _CONFIG_OPTION,
    database_url: str | None = _DATABASE_URL_OPTION,
    account_id: str | None = _ACCOUNT_ID_OPTION,
    runs_dir: Path = _RUNS_DIR_OPTION,
    mailbox: Path | None = _MAILBOX_OPTION,
    known_item_ids: Path | None = _KNOWN_IDS_OPTION,
) -> None:
    """Run an experiment defined by a YAML config against the eval corpus."""
    experiment = _load_config(config)
    resolved_url = database_url or os.environ.get("ROSALIND_DATABASE_URL")
    if not resolved_url or not account_id:
        error_console.print(
            "[red]run needs --database-url (or $ROSALIND_DATABASE_URL) and "
            "--account-id for a populated eval corpus.[/red]"
        )
        raise typer.Exit(code=2)
    try:
        account = uuid.UUID(account_id)
    except ValueError as exc:
        error_console.print(f"[red]--account-id is not a UUID: {account_id}[/red]")
        raise typer.Exit(code=2) from exc

    overrides = experiment.overrides.to_pipeline_overrides()
    executor = LiveSearchExecutor.from_database_url(
        resolved_url, account, overrides=overrides, mode=experiment.overrides.mode
    )
    known = _resolve_known_item_ids(mailbox, known_item_ids)
    try:
        outcome = run_experiment(
            experiment, executor=executor, runs_dir=runs_dir, known_item_ids=known
        )
    finally:
        executor.close()
    _print_run(outcome)


@app.command()
def compare(
    run_a: Path = _RUN_DIR_ARG,
    run_b: Path = _RUN_DIR_ARG,
) -> None:
    """Compare two runs and report metric deltas with confidence intervals."""
    summary_a = load_run(run_a)
    summary_b = load_run(run_b)
    deltas = compare_runs(summary_a, summary_b)
    if not deltas:
        error_console.print("[yellow]no comparable per-question metrics[/yellow]")
        raise typer.Exit(code=2)

    table = Table(
        title=f"{summary_a.manifest['run_id']}  vs  {summary_b.manifest['run_id']}"
    )
    for column in ("metric", "A", "B", "delta", "95% CI", "p"):
        table.add_column(column)
    for delta in deltas:
        ci = (
            f"[{delta.ci_low:.3f}, {delta.ci_high:.3f}]"
            if delta.ci_low is not None and delta.ci_high is not None
            else "-"
        )
        p = f"{delta.p_value:.3f}" if delta.p_value is not None else "-"
        table.add_row(
            delta.metric,
            f"{delta.a:.3f}",
            f"{delta.b:.3f}",
            f"{delta.delta:+.3f}",
            ci,
            p,
        )
    console.print(table)


@app.command("validate-dataset")
def validate_dataset(
    dataset: Path = _DATASET_ARG,
    mailbox: Path | None = _MAILBOX_OPTION,
    known_item_ids: Path | None = _KNOWN_IDS_OPTION,
) -> None:
    """Validate a JSONL dataset (schema, splits, and corpus existence)."""
    try:
        records = dataset_mod.load_dataset(dataset)
    except ValueError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    known = _resolve_known_item_ids(mailbox, known_item_ids)
    issues = validate.validate_dataset(records, known_item_ids=known)
    _print_issues(issues)

    errors = [issue for issue in issues if issue.level == "error"]
    warnings = [issue for issue in issues if issue.level == "warning"]
    if errors:
        error_console.print(
            f"[red]{len(errors)} error(s)[/red], {len(warnings)} warning(s)"
        )
        raise typer.Exit(code=2)
    console.print(
        f"[green]ok[/green]: {len(records)} questions, {len(warnings)} warning(s)"
    )


@app.command("generate-questions")
def generate_questions(
    output: Path = _OUTPUT_OPTION,
    mailbox: Path | None = _GEN_MAILBOX_OPTION,
    model: str = _MODEL_OPTION,
    base_url: str = _BASE_URL_OPTION,
    limit: int | None = _LIMIT_OPTION,
) -> None:
    """Write draft questions from a mailbox using a local Ollama model."""
    source = mailbox if mailbox is not None else corpus.mailbox_path()
    passages = list(corpus.iter_passages(source))
    if limit is not None:
        passages = passages[:limit]
    if not passages:
        error_console.print("[red]no passages found in the mailbox[/red]")
        raise typer.Exit(code=2)

    try:
        llm = make_ollama_llm(model=model, base_url=base_url)
    except RuntimeError as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    records = generate.generate_questions(passages, llm)
    dataset_mod.write_dataset(output, records)
    console.print(f"[green]wrote[/green] {len(records)} draft questions to {output}")


def _load_config(path: Path) -> ExperimentConfig:
    try:
        return load_config(path)
    except (TypeError, ValueError, ValidationError) as exc:
        error_console.print(f"[red]invalid config {path}:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _resolve_known_item_ids(
    mailbox: Path | None, known_item_ids: Path | None
) -> frozenset[str] | None:
    if mailbox is not None:
        return corpus.known_item_ids_from_mailbox(mailbox)
    if known_item_ids is not None:
        return _read_known_item_ids(known_item_ids)
    return None


def _read_known_item_ids(path: Path) -> frozenset[str]:
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        error_console.print(f"[red]{path}: invalid JSON: {exc}[/red]")
        raise typer.Exit(code=2) from exc
    if isinstance(raw, dict):
        raw = raw.get("item_ids", [])
    if not isinstance(raw, list):
        error_console.print(
            f'[red]{path}: expected a list of item ids or {{"item_ids": [...]}}[/red]'
        )
        raise typer.Exit(code=2)
    return frozenset(str(item) for item in raw)


def _print_run(outcome: RunOutcome) -> None:
    overall = outcome.metrics.get("overall", {})
    console.print(
        f"[green]run[/green] {outcome.manifest['run_id']} -> {outcome.paths.root}"
    )
    table = Table(title="overall metrics")
    table.add_column("metric")
    table.add_column("value")
    for key, value in overall.items():
        table.add_row(key, f"{value:.3f}" if isinstance(value, float) else str(value))
    console.print(table)

    funnel = outcome.metrics.get("funnel", {})
    if funnel:
        funnel_table = Table(title="failure funnel")
        funnel_table.add_column("label")
        funnel_table.add_column("count")
        for label, count in funnel.items():
            funnel_table.add_row(label, str(count))
        console.print(funnel_table)

    for warning in outcome.warnings:
        console.print(f"[yellow]warning[/yellow] {warning}")


def _print_issues(issues: list[ValidationIssue]) -> None:
    if not issues:
        return
    table = Table(title="validation issues")
    table.add_column("level")
    table.add_column("code")
    table.add_column("question")
    table.add_column("message")
    for issue in issues:
        color = "red" if issue.level == "error" else "yellow"
        table.add_row(
            f"[{color}]{issue.level}[/{color}]",
            issue.code,
            issue.question_id or "-",
            issue.message,
        )
    console.print(table)
