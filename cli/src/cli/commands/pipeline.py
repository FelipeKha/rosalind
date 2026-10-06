"""`rosalind pipeline ...` commands.

The offline pipeline turns raw archive files into searchable data. It currently
runs only the record-split stage; later stages (parse, canonicalize, enrich,
chunk, embed) will slot in behind the same entry point.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from cli import output
from cli.client import ApiClientError
from cli.client import processing as client
from cli.commands import _format

pipeline_app = typer.Typer(help="Run the offline data pipeline.")


@pipeline_app.command("run")
def run(
    import_id: str,
    stage: str | None = typer.Option(
        None,
        "--stage",
        help="Run a single pipeline stage (split, canonicalize, reconcile, enrich, attachments, chunk).",
    ),
) -> None:
    """Run the offline pipeline for an import."""
    failed = 0
    last: dict[str, Any] | None = None
    try:
        events = client.stream_pipeline(import_id, stage=stage)
        for event in events:
            last = event
            failed = int(event.get("failed", failed))
            _render_event(event)
    except ApiClientError as exc:
        typer.echo(f"Failed to run pipeline: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if last is None:
        return

    if output.json_mode:
        return

    if last.get("stage") == "error":
        typer.echo(f"Pipeline error: {last.get('message')}", err=True)
        raise typer.Exit(code=1)

    typer.echo("")
    typer.echo("Pipeline complete")
    typer.echo(f"  Processed: {last.get('processed', 0)} messages")
    typer.echo(f"  Created:   {last.get('created', 0)}")
    typer.echo(f"  Reused:    {last.get('reused', 0)}")
    typer.echo(f"  Failed:    {failed}")
    if failed:
        raise typer.Exit(code=1)


def _render_event(event: dict[str, Any]) -> None:
    stage = event.get("stage")

    if output.json_mode:
        typer.echo(json.dumps(event))
        return

    if stage == "starting":
        total_files = int(event.get("total_files", 0))
        total_bytes = int(event.get("total_bytes", 0))
        typer.echo(
            f"Splitting {total_files} mbox file(s) ({_format.human_size(total_bytes)})"
        )
    elif stage == "splitting":
        typer.echo(
            f"  {event.get('file')}: {event.get('processed', 0)} messages "
            f"· {event.get('created', 0)} new · {event.get('reused', 0)} reused "
            f"· {event.get('failed', 0)} failed"
        )
    elif stage == "done":
        typer.echo(
            f"Done: {event.get('processed', 0)} messages "
            f"· {event.get('created', 0)} new · {event.get('reused', 0)} reused "
            f"· {event.get('failed', 0)} failed"
        )
    elif stage == "canonicalizing":
        typer.echo(
            f"  canonicalizing: {event.get('processed', 0)} records "
            f"· {event.get('created', 0)} new · {event.get('reused', 0)} reused "
            f"· {event.get('failed', 0)} failed"
        )
    elif stage == "canonicalized":
        typer.echo(
            f"Canonicalized: {event.get('processed', 0)} messages "
            f"· {event.get('created', 0)} new · {event.get('reused', 0)} reused "
            f"· {event.get('failed', 0)} failed"
        )
    elif stage == "reconciling":
        typer.echo("Reconciling threads...")
    elif stage == "reconciled":
        details = event.get("details") or {}
        typer.echo(
            "Reconciled threads: "
            f"{details.get('messages_reassigned', 0)} reassigned · "
            f"{details.get('threads_created', 0)} created · "
            f"{details.get('threads_removed', 0)} removed"
        )
    elif stage == "extracting_attachments":
        typer.echo("Extracting attachment text...")
    elif stage == "attachments_extracted":
        details = event.get("details") or {}
        typer.echo(
            "Attachments extracted: "
            f"{details.get('done', 0)} done · "
            f"{details.get('failed', 0)} failed · "
            f"{details.get('needs_ocr', 0)} needs_ocr"
        )
    elif stage == "chunking":
        typer.echo("Chunking derived text...")
    elif stage == "chunked":
        details = event.get("details") or {}
        typer.echo(
            "Chunked: "
            f"{details.get('chunks_written', 0)} written · "
            f"{details.get('chunks_unchanged', 0)} unchanged · "
            f"{details.get('skipped_not_ready', 0)} skipped"
        )
    elif stage == "error":
        typer.echo(f"Error: {event.get('message')}", err=True)
