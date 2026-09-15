"""`rosalind import google <path>` command."""

from pathlib import Path
from typing import cast

import typer

from cli import client
from cli.ingestion import discovery
from cli.ingestion import manifest as manifest_builder
from cli.storage.s3 import S3ObjectStorage

import_app = typer.Typer(help="Import data from a provider.")


@import_app.command("google")
def google(path: Path) -> None:
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

    files = discovery.discover(path)

    storage = S3ObjectStorage()
    typer.echo(f"Uploading {len(files)} files to {bucket}...")
    try:
        for info in files:
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


def _print_result(result: dict[str, object], bucket: str) -> None:
    typer.echo("Import completed")
    typer.echo(f"ID:        {result['import_id']}")
    typer.echo("Source:    Google Takeout")
    typer.echo(f"Files:     {result['file_count']}")
    typer.echo(f"Size:      {_human_size(cast(int, result['total_size']))}")
    typer.echo(f"Hash:      {result['import_hash']}")
    typer.echo("")
    typer.echo(f"Stored in object storage bucket {bucket!r}.")


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
