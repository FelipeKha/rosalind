"""``rosalind-eval`` command-line interface.

Phase 2 scaffolds the three commands and the experiment-config loader. The
``run`` and ``compare`` execution bodies land in Phase 4; ``validate-dataset``
gets full schema validation in Phase 3. For now ``run`` loads and validates a
config and reports what it resolved, and ``validate-dataset`` does a structural
JSONL check.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from rosalind_eval.config import ExperimentConfig, load_config

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


def main() -> None:
    """Console entry point (``rosalind-eval``)."""
    app()


@app.command()
def run(config: Path = _CONFIG_OPTION) -> None:
    """Run an experiment defined by a YAML config."""
    experiment = _load(config)
    _print_experiment(experiment)
    console.print(
        "[yellow]run: execution lands in Phase 4; config validated only.[/yellow]"
    )


@app.command()
def compare(
    run_a: Path = _RUN_DIR_ARG,
    run_b: Path = _RUN_DIR_ARG,
) -> None:
    """Compare two runs and report metric deltas with confidence intervals."""
    console.print(f"comparing [bold]{run_a}[/bold] and [bold]{run_b}[/bold]")
    console.print(
        "[yellow]compare: execution lands in Phase 4; nothing computed.[/yellow]"
    )


@app.command("validate-dataset")
def validate_dataset(dataset: Path = _DATASET_ARG) -> None:
    """Validate a JSONL dataset (full schema checks land in Phase 3)."""
    count = 0
    with dataset.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                error_console.print(f"line {line_number}: invalid JSON: {exc}")
                raise typer.Exit(code=2) from exc
            if not isinstance(record, dict):
                error_console.print(
                    f"line {line_number}: expected a JSON object, got "
                    f"{type(record).__name__}"
                )
                raise typer.Exit(code=2)
            count += 1
    console.print(f"[green]{count}[/green] records in {dataset}")


def _load(path: Path) -> ExperimentConfig:
    try:
        return load_config(path)
    except (TypeError, ValueError, ValidationError) as exc:
        error_console.print(f"[red]invalid config {path}:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _print_experiment(experiment: ExperimentConfig) -> None:
    table = Table(title=experiment.name, show_header=False)
    table.add_column("field", style="cyan")
    table.add_column("value")
    table.add_row("dataset", str(experiment.dataset))
    if experiment.description:
        table.add_row("description", experiment.description)
    overrides = experiment.overrides
    for field_name in (
        "mode",
        "lexical_k",
        "semantic_k",
        "fused_k",
        "rerank_k",
        "window_k",
        "reranker",
        "disable_reranker",
        "chunk_prefix",
    ):
        value = getattr(overrides, field_name)
        if value is not None:
            table.add_row(field_name, str(value))
    if overrides.fusion is not None:
        table.add_row("fusion.strategy", overrides.fusion.strategy)
        table.add_row("fusion.rrf_k", str(overrides.fusion.rrf_k))
    console.print(table)
