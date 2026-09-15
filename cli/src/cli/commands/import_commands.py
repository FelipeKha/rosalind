"""`rosalind import ...` commands."""

from pathlib import Path
from typing import cast

import typer

from cli import client
from cli.commands import _format
from cli.ingestion import discovery
from cli.ingestion import manifest as manifest_builder
from cli.storage.s3 import S3ObjectStorage

import_app = typer.Typer(help="Import data from a provider.")

create_app = typer.Typer(help="Create a new import.")


@create_app.command("google")
def create_google(path: Path) -> None:
    """Import a Google Takeout directory."""
    if not path.exists():
        typer.echo(f"Path does not exist: {path}", err=True)
        raise typer.Exit(code=1)
    if not path.is_dir():
        typer.echo(f"Path is not a directory: {path}", err=True)
        raise typer.Exit(code=1)

    try:
        created = client.create_import("google", "takeout")
    except client.ApiClientError as exc:
        typer.echo(f"Failed to create import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    import_id = str(created["import_id"])
    storage_prefix = str(created["storage_prefix"])
    bucket = str(created["bucket"])

    typer.echo("Discovering files...")
    paths = discovery.discover_paths(path)
    typer.echo(f"Discovered {len(paths)} files.")

    with typer.progressbar(
        paths,
        label="Hashing",
        item_show_func=lambda entry: entry.name if entry else "",
    ) as progress:
        files = [discovery.file_info(entry, path) for entry in progress]

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
    except client.ApiClientError as exc:
        typer.echo(f"Failed to complete import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _print_result(result, bucket)


@import_app.command("list")
def list_imports() -> None:
    """List all imports."""
    try:
        imports = client.list_imports()
    except client.ApiClientError as exc:
        typer.echo(f"Failed to list imports: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not imports:
        typer.echo("No imports found.")
        return

    headers = ("ID", "SOURCE", "TYPE", "STATUS", "CREATED", "FILES", "SIZE")
    rows = [
        (
            str(item["import_id"]),
            str(item["source"]),
            str(item["type"]),
            str(item["status"]),
            _format.format_datetime(item["created_at"]),
            f"{item['file_count']} files",
            _format.human_size(cast(int, item["total_size"])),
        )
        for item in imports
    ]

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]

    typer.echo("  ".join(header.ljust(width) for header, width in zip(headers, widths)))
    for row in rows:
        typer.echo("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))


@import_app.command("delete")
def delete_import(
    import_id: str,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt."
    ),
) -> None:
    """Delete an import and its raw files."""
    if not yes:
        typer.confirm(
            f"Delete import {import_id} and all of its files? This cannot be undone.",
            abort=True,
        )

    try:
        client.delete_import(import_id)
    except client.ApiClientError as exc:
        typer.echo(f"Failed to delete import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Import {import_id} deleted.")


import_app.add_typer(create_app, name="create")


def _print_result(result: dict[str, object], bucket: str) -> None:
    typer.echo("Import completed")
    typer.echo(f"ID:        {result['import_id']}")
    typer.echo("Source:    Google Takeout")
    typer.echo(f"Files:     {result['file_count']}")
    typer.echo(f"Size:      {_format.human_size(cast(int, result['total_size']))}")
    typer.echo(f"Hash:      {result['import_hash']}")
    typer.echo("")
    typer.echo(f"Stored in object storage bucket {bucket!r}.")
