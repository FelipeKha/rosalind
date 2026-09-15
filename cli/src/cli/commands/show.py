"""`rosalind show <import_id>` command."""

from typing import cast

import typer

from cli import client
from cli.commands import _format


def show(import_id: str) -> None:
    """Inspect the files in an import."""
    try:
        detail = client.get_import(import_id)
    except client.ApiClientError as exc:
        typer.echo(f"Failed to get import: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"ID:        {detail['import_id']}")
    typer.echo(f"Source:    {detail['source']}")
    typer.echo(f"Type:      {detail['type']}")
    typer.echo(f"Status:    {detail['status']}")
    typer.echo(f"Files:     {detail['file_count']}")
    typer.echo(f"Size:      {_format.human_size(cast(int, detail['total_size']))}")
    typer.echo(f"Hash:      {detail['import_hash']}")
    typer.echo("")

    files = cast(list[dict[str, object]], detail["files"])
    for file_ in files:
        typer.echo(
            f"  {file_['path']}  ({_format.human_size(cast(int, file_['size']))})"
        )
