"""`rosalind process ...` commands."""

from __future__ import annotations

import typer

from cli import output
from cli.client import ApiClientError
from cli.client import processing as client
from cli.output import json as json_output

process_app = typer.Typer(help="Turn imported data into canonical data.")


@process_app.command("run")
def run(import_id: str) -> None:
    """Process an import into canonical data."""
    try:
        result = client.process_import(import_id)
    except ApiClientError as exc:
        typer.echo(f"Failed to process import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(result)
        return

    if result["result"] == "unsupported":
        typer.echo(f"Processing not available: {result['message']}")
        return

    typer.echo("Processing import completed")
    typer.echo(f"  People created:   {result['people_created']}")
    typer.echo(f"  Facts created:    {result['facts_created']}")
    typer.echo(f"  Facts reused:     {result['facts_reused']}")
    typer.echo(f"  Assertions added: {result['assertions_created']}")
