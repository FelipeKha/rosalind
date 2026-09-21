"""`rosalind source ...` commands."""

from __future__ import annotations

import time
import uuid
import webbrowser
from typing import Annotated

import typer

from cli import output
from cli.client import ApiClientError
from cli.client import sources as client
from cli.output import json as json_output
from cli.output import tables

source_app = typer.Typer(help="Manage connected data providers.")


@source_app.command("list")
def list_sources() -> None:
    """List connected and available sources."""
    try:
        sources = client.list_sources()
    except ApiClientError as exc:
        typer.echo(f"Failed to list sources: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(sources)
        return

    if not sources:
        typer.echo("No sources found.")
        return

    headers = ("NAME", "PROVIDER", "STATUS", "DISPLAY NAME")
    rows = [
        (
            item["name"] or "-",
            item["provider"],
            item["status"],
            item["display_name"] or "-",
        )
        for item in sources
    ]
    tables.render_table(headers, rows)


@source_app.command("show")
def show_source(source: str) -> None:
    """Show details for a source (by name or id)."""
    source_id = _resolve_source_id(source)
    try:
        detail = client.get_source(source_id)
    except ApiClientError as exc:
        typer.echo(f"Failed to get source: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(detail)
        return

    typer.echo(f"Name:      {detail['name'] or '-'}")
    typer.echo(f"Provider:  {detail['provider']}")
    typer.echo(f"Status:    {detail['status']}")
    typer.echo(f"Account:   {detail.get('account_identifier') or '-'}")
    typer.echo(f"Display:   {detail['display_name'] or '-'}")


@source_app.command("create")
def create_source(
    provider: Annotated[str, typer.Argument(help="Provider, e.g. google.")],
    name: Annotated[str, typer.Option("--name", help="Source name (slug).")],
) -> None:
    """Declare a source without connecting (e.g. for Takeout imports)."""
    try:
        created = client.create_source(provider, name)
    except ApiClientError as exc:
        typer.echo(f"Failed to create source: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(created)
        return

    typer.echo(f"Created source {created['name']!r} ({created['provider']}).")


@source_app.command("connect")
def connect(
    provider: Annotated[str, typer.Argument(help="Provider, e.g. google.")],
    name: Annotated[
        str | None, typer.Option("--name", help="Source name (slug).")
    ] = None,
    open_browser: Annotated[
        bool,
        typer.Option(
            "--browser/--no-browser",
            help="Open the authorization URL in a browser.",
        ),
    ] = True,
) -> None:
    """Authorize Rosalind to access a provider account."""
    try:
        created = client.connect(provider, name)
    except ApiClientError as exc:
        typer.echo(f"Failed to start {provider} authorization: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    auth_url = str(created["auth_url"])
    state = str(created["state"])

    typer.echo(f"Authorize Rosalind by visiting this URL:\n{auth_url}")
    if open_browser:
        webbrowser.open(auth_url)

    typer.echo("Waiting for authorization...")
    _poll_status(state)


@source_app.command("disconnect")
def disconnect(source: str) -> None:
    """Revoke access for a source; imported data is left untouched."""
    source_id = _resolve_source_id(source)
    try:
        result = client.disconnect(source_id)
    except ApiClientError as exc:
        typer.echo(f"Failed to disconnect source: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output.json_mode:
        json_output.render_json(result)
        return

    if result.get("status") == "already_disconnected":
        typer.echo("Source is not connected.")
    elif result.get("revoked"):
        typer.echo("Disconnected. Historical imports and data were retained.")
    else:
        typer.echo(
            "Disconnected locally; provider token revocation failed. "
            "Historical imports and data were retained."
        )


def _poll_status(state: str, timeout: float = 120.0, interval: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = client.connect_status(state)
        except ApiClientError as exc:
            typer.echo(f"Failed to check authorization status: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        status = str(result["status"])
        if status == "connected":
            display = result.get("display_name") or "your account"
            typer.echo(f"Connected: {display}")
            return
        if status in {"expired", "not_found"}:
            typer.echo(f"Authorization failed: {status}", err=True)
            raise typer.Exit(code=1)

        if time.monotonic() >= deadline:
            typer.echo("Timed out waiting for authorization.", err=True)
            raise typer.Exit(code=1)

        time.sleep(interval)


def _resolve_source_id(identifier: str) -> str:
    try:
        uuid.UUID(identifier)
        return identifier
    except ValueError:
        pass

    try:
        sources = client.list_sources()
    except ApiClientError as exc:
        typer.echo(f"Failed to list sources: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    match = [s for s in sources if s.get("name") == identifier]
    if not match:
        typer.echo(f"Source {identifier!r} not found.", err=True)
        raise typer.Exit(code=1)
    return str(match[0]["source_id"])
