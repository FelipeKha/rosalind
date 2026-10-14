"""`rosalind import ...` commands."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from cli import output
from cli.client import ApiClientError
from cli.client import imports as client
from cli.commands import _format
from cli.ingestion import discovery
from cli.ingestion import manifest as manifest_builder
from cli.output import json as json_output
from cli.output import tables
from cli.storage.s3 import S3ObjectStorage

import_app = typer.Typer(help="Bring source data into Rosalind.")


class Source(str, Enum):
    google = "google"
    none = "none"


class Via(str, Enum):
    file = "file"
    api = "api"


@import_app.command("create")
def create(
    source: Annotated[
        Source,
        typer.Option("--source", help="Source to import from: google or none."),
    ] = Source.none,
    via: Annotated[
        Via,
        typer.Option(
            "--via",
            help="How data enters Rosalind: file (upload a local file/folder) or api.",
        ),
    ] = Via.file,
    path: Annotated[
        Path | None,
        typer.Argument(help="File or folder to upload (required for --via file)."),
    ] = None,
) -> None:
    """Create an import from a source."""
    if via is Via.api:
        if source is not Source.google:
            typer.echo("--via api requires --source google.", err=True)
            raise typer.Exit(code=2)
        if path is not None:
            typer.echo("--via api does not take a path.", err=True)
            raise typer.Exit(code=2)
        _create_api(source.value)
    else:
        _create_file(source.value, path)


def _create_file(source: str, path: Path | None) -> None:
    if path is None:
        typer.echo("A path is required for --via file.", err=True)
        raise typer.Exit(code=2)
    if not path.exists():
        typer.echo(f"Path does not exist: {path}", err=True)
        raise typer.Exit(code=1)

    try:
        created = client.create_import(source, "file")
    except ApiClientError as exc:
        typer.echo(f"Failed to create import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    import_id = str(created["import_id"])
    storage_prefix = str(created["storage_prefix"])
    bucket = str(created["bucket"])

    typer.echo("Discovering files...")
    files = discovery.discover(path)
    typer.echo(f"Discovered {len(files)} files.")

    storage = S3ObjectStorage()
    try:
        with typer.progressbar(
            files,
            label="Uploading",
            item_show_func=lambda info: info.path if info else "",
        ) as progress:
            for info in progress:
                storage.upload_file(
                    info.local_path,
                    bucket,
                    f"{storage_prefix}/{info.path}",
                )
    except Exception as exc:  # boto3 raises several client error types
        typer.echo(f"Upload failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        result = client.complete_import(
            import_id, manifest_builder.build_manifest(files)
        )
    except ApiClientError as exc:
        typer.echo(f"Failed to complete import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _print_file_result(result, bucket)


def _create_api(source: str) -> None:
    try:
        result = client.create_import(source, "api")
    except ApiClientError as exc:
        typer.echo(f"Failed to create import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(result)
        return

    typer.echo("Import completed")
    typer.echo(f"ID:          {result['import_id']}")
    typer.echo(f"Source:      {result['source_name']}")
    typer.echo(f"Via:         {result['via']}")
    typer.echo(f"Ingestion:   {result['ingestion_status']}")
    typer.echo(f"Processing:  {result['processing_status']}")


@import_app.command("show")
def show(import_id: str) -> None:
    """Inspect the files in an import."""
    try:
        detail = client.get_import(import_id)
    except ApiClientError as exc:
        typer.echo(f"Failed to get import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(detail)
        return

    typer.echo(f"ID:         {detail['import_id']}")
    typer.echo(f"Source:     {detail['source_name'] or '-'}")
    typer.echo(f"Via:        {detail['via']}")
    typer.echo(f"Ingestion:  {detail['ingestion_status']}")
    typer.echo(f"Processing: {detail['processing_status']}")
    typer.echo(f"Files:      {detail['file_count']}")
    typer.echo(f"Size:       {_format.human_size(cast(int, detail['total_size']))}")
    typer.echo(f"Hash:       {detail['import_hash']}")
    typer.echo("")

    for file_ in cast(list[dict[str, Any]], detail["files"]):
        typer.echo(
            f"  {file_['path']}  ({_format.human_size(cast(int, file_['size']))})"
        )


@import_app.command("list")
def list_imports() -> None:
    """List all imports."""
    try:
        imports = client.list_imports()
    except ApiClientError as exc:
        typer.echo(f"Failed to list imports: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(imports)
        return

    if not imports:
        typer.echo("No imports found.")
        return

    headers = ("ID", "SOURCE", "VIA", "INGESTION", "PROCESSING", "FILES", "SIZE")
    rows = [
        (
            str(item["import_id"]),
            str(item["source_name"] or "-"),
            str(item["via"]),
            str(item["ingestion_status"]),
            str(item["processing_status"]),
            str(item["file_count"]),
            _format.human_size(cast(int, item["total_size"])),
        )
        for item in imports
    ]
    tables.render_table(headers, rows)


@import_app.command("delete")
def delete_import(
    import_id: str,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Delete an import and its raw files."""
    if not yes:
        typer.confirm(
            f"Delete import {import_id} and all of its files? This cannot be undone.",
            abort=True,
        )

    try:
        client.delete_import(import_id)
    except ApiClientError as exc:
        typer.echo(f"Failed to delete import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Import {import_id} deleted.")


def _print_file_result(result: dict[str, Any], bucket: str) -> None:
    if output.json_mode:
        json_output.render_json(result)
        return

    typer.echo("Import completed")
    typer.echo(f"ID:         {result['import_id']}")
    typer.echo(f"Source:     {result['source_name'] or '-'}")
    typer.echo(f"Via:        {result['via']}")
    typer.echo(f"Ingestion:  {result['ingestion_status']}")
    typer.echo(f"Processing: {result['processing_status']}")
    typer.echo(f"Files:      {result['file_count']}")
    typer.echo(f"Size:       {_format.human_size(cast(int, result['total_size']))}")
    typer.echo(f"Hash:       {result['import_hash']}")
    typer.echo("")
    typer.echo(f"Stored in object storage bucket {bucket!r}.")
