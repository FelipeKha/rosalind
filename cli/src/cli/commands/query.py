"""`rosalind query ...` commands."""

from __future__ import annotations

from typing import Annotated

import typer

from cli import output
from cli.client import ApiClientError
from cli.client import query as client
from cli.output import json as json_output
from cli.output import tables

query_app = typer.Typer(help="Query canonical data.")


@query_app.command("people")
def people(
    search: Annotated[
        str | None, typer.Option("--search", help="Search by name or email.")
    ] = None,
) -> None:
    """List known people, optionally filtered by a search query."""
    try:
        if search is not None:
            results = client.search_people(search)
        else:
            results = client.list_people()
    except ApiClientError as exc:
        typer.echo(f"Failed to query people: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(results)
        return

    if not results:
        typer.echo("No people found.")
        return

    headers = ("ID", "NAME", "EMAIL")
    rows = [
        (
            str(item["person_id"]),
            item["display_name"] or "-",
            item["primary_email"] or "-",
        )
        for item in results
    ]
    tables.render_table(headers, rows)


@query_app.command("person")
def person(person_id: str) -> None:
    """Show one person by id."""
    try:
        detail = client.get_person(person_id)
    except ApiClientError as exc:
        typer.echo(f"Failed to get person: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(detail)
        return

    typer.echo(detail["display_name"] or "-")
    if detail.get("primary_email"):
        typer.echo(f"Email:    {detail['primary_email']}")
    if detail.get("gender"):
        typer.echo(f"Gender:   {detail['gender']}")
    if detail.get("locale"):
        typer.echo(f"Locale:   {detail['locale']}")
    birth = _birth(detail)
    if birth:
        typer.echo(f"Birthday: {birth}")


def _birth(detail: dict) -> str | None:
    parts = [
        detail.get("birth_year"),
        detail.get("birth_month"),
        detail.get("birth_day"),
    ]
    if all(part is None for part in parts):
        return None
    return "-".join(str(part) for part in parts if part is not None)
