"""Human-readable table rendering."""

from __future__ import annotations

from collections.abc import Sequence

import typer


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    typer.echo("  ".join(header.ljust(width) for header, width in zip(headers, widths)))
    for row in rows:
        typer.echo("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))
